import time
import math
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from ultralytics import YOLO

from app.config import Settings, settings as default_settings

class VisionDetector:
    """
    Real-time multi-modal computer vision detector for observable study behaviors.
    Combines MediaPipe Tasks Face Landmarker for facial orientation, eye tracking,
    and yawn detection with Ultralytics YOLO for mobile phone detection.
    """
    
    # Landmark indices for Left Eye EAR (outer, top1, top2, inner, bot2, bot1)
    LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    
    # Landmark indices for Right Eye EAR (inner, top1, top2, outer, bot2, bot1)
    RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380]

    # Mouth landmark indices for Mouth Aspect Ratio (MAR) yawn estimation
    # Inner lip vertical pairs: (13, 14), (81, 178), (311, 402)
    # Horizontal corners: (78, 308)
    MOUTH_VERTICAL_PAIRS = [(13, 14), (81, 178), (311, 402)]
    MOUTH_HORIZONTAL = (78, 308)
    
    # Simplified landmark indices for lightweight client canvas rendering
    FACE_CONTOUR_INDICES = [
        10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
        397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
        172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109
    ]
    LEFT_EYE_CONTOUR = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
    RIGHT_EYE_CONTOUR = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
    LIPS_CONTOUR = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
    INNER_LIPS_CONTOUR = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]
    NOSE_POINTS = [1, 2, 98, 327]

    def __init__(self, custom_settings: Settings = None):
        self.settings = custom_settings or default_settings
        
        # 1. Initialize MediaPipe Face Landmarker
        base_options = python.BaseOptions(model_asset_path=self.settings.face_landmarker_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_facial_transformation_matrixes=True,
            output_face_blendshapes=True,
            num_faces=1
        )
        self.face_landmarker = vision.FaceLandmarker.create_from_options(options)
        
        # 2. Initialize YOLO for cell phone detection (class 67)
        self.yolo_model = YOLO(self.settings.yolo_model_path)
        
        # 3. Cache & Interval State
        self.frame_counter = 0
        self.last_phone_boxes = []
        self.last_phone_detected = False
        self.last_phone_max_conf = 0.0
        
        # 4. Calibration Baselines (offsets)
        self.calibrated = False
        self.baseline_yaw = 0.0
        self.baseline_pitch = 0.0
        self.baseline_ear = 0.28

    def calibrate_baseline(self, frame_bgr):
        """
        Calibrates neutral gaze and resting eye openness for the student's unique webcam angle.
        """
        h, w, _ = frame_bgr.shape
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = self.face_landmarker.detect(mp_img)
        
        if not res.face_landmarks:
            return False, "No face detected for calibration. Please look directly at the screen."
        
        landmarks = res.face_landmarks[0]
        left_ear = self._compute_ear(landmarks, self.LEFT_EYE_INDICES)
        right_ear = self._compute_ear(landmarks, self.RIGHT_EYE_INDICES)
        avg_ear = (left_ear + right_ear) / 2.0
        
        yaw, pitch, _ = self._compute_head_pose(res, landmarks, w, h)
        
        self.baseline_yaw = yaw
        self.baseline_pitch = pitch
        self.baseline_ear = avg_ear
        self.calibrated = True
        
        return True, {
            "baseline_yaw": round(self.baseline_yaw, 2),
            "baseline_pitch": round(self.baseline_pitch, 2),
            "baseline_ear": round(self.baseline_ear, 3)
        }

    def _compute_ear(self, landmarks, eye_indices):
        """
        Eye Aspect Ratio (EAR) formula:
        EAR = (||p2 - p6|| + ||p3 - p5||) / (2 * ||p1 - p4||)
        """
        p1 = np.array([landmarks[eye_indices[0]].x, landmarks[eye_indices[0]].y])
        p2 = np.array([landmarks[eye_indices[1]].x, landmarks[eye_indices[1]].y])
        p3 = np.array([landmarks[eye_indices[2]].x, landmarks[eye_indices[2]].y])
        p4 = np.array([landmarks[eye_indices[3]].x, landmarks[eye_indices[3]].y])
        p5 = np.array([landmarks[eye_indices[4]].x, landmarks[eye_indices[4]].y])
        p6 = np.array([landmarks[eye_indices[5]].x, landmarks[eye_indices[5]].y])

        v1 = np.linalg.norm(p2 - p6)
        v2 = np.linalg.norm(p3 - p5)
        horizontal = np.linalg.norm(p1 - p4)

        if horizontal < 1e-6:
            return 0.0
        return float((v1 + v2) / (2.0 * horizontal))

    def _compute_mar(self, landmarks):
        """
        Mouth Aspect Ratio (MAR) for yawn detection:
        MAR = (||p13 - p14|| + ||p81 - p178|| + ||p311 - p402||) / (2 * ||p78 - p308||)
        """
        p13 = np.array([landmarks[13].x, landmarks[13].y])
        p14 = np.array([landmarks[14].x, landmarks[14].y])
        p81 = np.array([landmarks[81].x, landmarks[81].y])
        p178 = np.array([landmarks[178].x, landmarks[178].y])
        p311 = np.array([landmarks[311].x, landmarks[311].y])
        p402 = np.array([landmarks[402].x, landmarks[402].y])
        
        c_left = np.array([landmarks[78].x, landmarks[78].y])
        c_right = np.array([landmarks[308].x, landmarks[308].y])

        v1 = np.linalg.norm(p13 - p14)
        v2 = np.linalg.norm(p81 - p178)
        v3 = np.linalg.norm(p311 - p402)
        h = np.linalg.norm(c_left - c_right)

        if h < 1e-6:
            return 0.0
        return float((v1 + v2 + v3) / (2.0 * h))

    def _compute_mouth_area(self, landmarks, img_w, img_h):
        """
        Calculates pixel area of extended mesh polygon around the mouth opening.
        """
        pts = np.array([[landmarks[i].x * img_w, landmarks[i].y * img_h] for i in self.INNER_LIPS_CONTOUR], dtype=np.float32)
        area = cv2.contourArea(pts)
        return float(area)

    def _compute_head_pose(self, res, landmarks, img_w, img_h):
        """
        Computes head orientation (pitch, yaw, roll in degrees).
        Uses MediaPipe's calibrated facial transformation matrix if available,
        or solves PnP using key 3D facial landmarks.
        """
        if res.facial_transformation_matrixes and len(res.facial_transformation_matrixes) > 0:
            mat = res.facial_transformation_matrixes[0]
            R = mat[:3, :3]
            angles, _, _, _, _, _ = cv2.RQDecomp3x3(R)
            pitch, yaw, roll = float(angles[0]), float(angles[1]), float(angles[2])
            return yaw, pitch, roll
        
        # Fallback to solvePnP
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip (1)
            (0.0, -330.0, -65.0),        # Chin (152)
            (-225.0, 170.0, -135.0),     # Left eye outer corner (33)
            (225.0, 170.0, -135.0),      # Right eye outer corner (263)
            (-150.0, -150.0, -125.0),    # Left mouth corner (61)
            (150.0, -150.0, -125.0)      # Right mouth corner (291)
        ], dtype=np.float64)

        key_indices = [1, 152, 33, 263, 61, 291]
        img_pts = np.array([[landmarks[i].x * img_w, landmarks[i].y * img_h] for i in key_indices], dtype=np.float64)

        focal_length = img_w
        cam_mat = np.array([[focal_length, 0, img_w / 2], [0, focal_length, img_h / 2], [0, 0, 1]], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        ret, rvec, tvec = cv2.solvePnP(model_points, img_pts, cam_mat, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE)
        if ret:
            rmat, _ = cv2.Rodrigues(rvec)
            angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
            return float(angles[1]), float(angles[0]), float(angles[2])
        
        return 0.0, 0.0, 0.0

    def _compute_gaze_projection(self, yaw_deg, pitch_deg, nose_x, nose_y, img_w, img_h, length=80):
        yaw_rad = math.radians(yaw_deg)
        pitch_rad = math.radians(pitch_deg)

        dx = math.sin(yaw_rad) * length
        dy = -math.sin(pitch_rad) * length

        target_x = max(0, min(img_w, nose_x + dx))
        target_y = max(0, min(img_h, nose_y + dy))

        return {
            "origin": [round(nose_x, 1), round(nose_y, 1)],
            "target": [round(target_x, 1), round(target_y, 1)],
            "norm_origin": [round(nose_x / max(1, img_w), 4), round(nose_y / max(1, img_h), 4)],
            "norm_target": [round(target_x / max(1, img_w), 4), round(target_y / max(1, img_h), 4)]
        }

    def _extract_key_landmarks(self, landmarks, img_w, img_h):
        def get_coords(indices):
            return [[round(landmarks[i].x, 3), round(landmarks[i].y, 3)] for i in indices]

        xs = [landmarks[i].x for i in self.FACE_CONTOUR_INDICES]
        ys = [landmarks[i].y for i in self.FACE_CONTOUR_INDICES]
        bbox = [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]

        return {
            "bbox": bbox,
            "left_eye": get_coords(self.LEFT_EYE_CONTOUR),
            "right_eye": get_coords(self.RIGHT_EYE_CONTOUR),
            "lips": get_coords(self.LIPS_CONTOUR),
            "inner_lips": get_coords(self.INNER_LIPS_CONTOUR),
            "contour": get_coords(self.FACE_CONTOUR_INDICES),
            "nose": get_coords(self.NOSE_POINTS)
        }

    def process_frame(self, frame_bgr, ear_thresh=None, yaw_thresh=None, pitch_thresh=None, phone_conf_thresh=None, mar_thresh=None):
        """
        Processes a single video frame and extracts all observable behavioral cues.
        """
        t0 = time.perf_counter()
        self.frame_counter += 1
        
        img_h, img_w, _ = frame_bgr.shape
        ear_cutoff = ear_thresh if ear_thresh is not None else self.settings.ear_threshold
        yaw_cutoff = yaw_thresh if yaw_thresh is not None else self.settings.head_yaw_threshold
        pitch_cutoff = pitch_thresh if pitch_thresh is not None else self.settings.head_pitch_threshold
        phone_cutoff = phone_conf_thresh if phone_conf_thresh is not None else self.settings.phone_confidence_threshold
        mar_cutoff = mar_thresh if mar_thresh is not None else self.settings.mar_threshold

        # --- 1. Face & Eye & Yawn Analysis (MediaPipe Tasks) ---
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        face_result = self.face_landmarker.detect(mp_img)

        face_detected = bool(face_result.face_landmarks and len(face_result.face_landmarks) > 0)
        
        left_ear = 0.0
        right_ear = 0.0
        avg_ear = 0.0
        eyes_closed = False
        mar = 0.0
        mouth_area = 0.0
        mouth_wide_open = False
        raw_yaw = 0.0
        raw_pitch = 0.0
        raw_roll = 0.0
        adj_yaw = 0.0
        adj_pitch = 0.0
        head_turned = False
        gaze_vector = None
        key_landmarks = None

        if face_detected:
            landmarks = face_result.face_landmarks[0]
            
            # Eye Aspect Ratio (EAR)
            left_ear = self._compute_ear(landmarks, self.LEFT_EYE_INDICES)
            right_ear = self._compute_ear(landmarks, self.RIGHT_EYE_INDICES)
            avg_ear = (left_ear + right_ear) / 2.0
            
            # Mouth Aspect Ratio (MAR) & Extended Mesh Area for Yawn Estimation
            mar = self._compute_mar(landmarks)
            mouth_area = self._compute_mouth_area(landmarks, img_w, img_h)

            # Blink & Jaw scores from blendshapes if available
            blink_left_score = 0.0
            blink_right_score = 0.0
            jaw_open_score = 0.0
            blend_map: dict = {}
            if face_result.face_blendshapes and len(face_result.face_blendshapes) > 0:
                blend_map = {b.category_name: b.score for b in face_result.face_blendshapes[0]}
                blink_left_score = blend_map.get("eyeBlinkLeft", 0.0)
                blink_right_score = blend_map.get("eyeBlinkRight", 0.0)
                jaw_open_score = blend_map.get("jawOpen", 0.0)

            # Eyes closed determination
            eyes_closed = bool(avg_ear < ear_cutoff or (blink_left_score > 0.65 and blink_right_score > 0.65))

            # Mouth wide open (yawn indicator via extended mesh area, MAR, or jaw score)
            mouth_wide_open = bool(mouth_area >= self.settings.mouth_area_threshold or mar >= mar_cutoff or jaw_open_score >= 0.50)

            # Head Pose (Yaw, Pitch, Roll)
            raw_yaw, raw_pitch, raw_roll = self._compute_head_pose(face_result, landmarks, img_w, img_h)
            
            # Apply user calibration offset
            adj_yaw = raw_yaw - self.baseline_yaw
            adj_pitch = raw_pitch - self.baseline_pitch

            # Facial profile asymmetry check (detects when head is turned sideways even if mask snaps)
            symmetry_turned = False
            if len(landmarks) > 454:
                d_left = abs(landmarks[1].x - landmarks[234].x)
                d_right = abs(landmarks[1].x - landmarks[454].x)
                sym_ratio = min(d_left, d_right) / max(d_left, d_right, 1e-6)
                if sym_ratio < 0.32:
                    symmetry_turned = True

            # Gaze deviation from blendshapes (only meaningful when blendshapes are available)
            gaze_deviated = False
            if blend_map:
                look_side_1 = blend_map.get("eyeLookInLeft", 0.0) + blend_map.get("eyeLookOutRight", 0.0)
                look_side_2 = blend_map.get("eyeLookOutLeft", 0.0) + blend_map.get("eyeLookInRight", 0.0)
                look_down = (blend_map.get("eyeLookDownLeft", 0.0) + blend_map.get("eyeLookDownRight", 0.0)) / 2.0
                look_up = (blend_map.get("eyeLookUpLeft", 0.0) + blend_map.get("eyeLookUpRight", 0.0)) / 2.0
                if look_side_1 > 0.85 or look_side_2 > 0.85 or look_down > 0.85 or look_up > 0.75:
                    gaze_deviated = True

            # Head turned away check: pose angle, facial profile asymmetry, or gaze deviation
            head_turned = bool(abs(adj_yaw) > yaw_cutoff or abs(adj_pitch) > pitch_cutoff or symmetry_turned or gaze_deviated)

            # Gaze direction vector from nose tip (landmark 1)
            nose_px_x = landmarks[1].x * img_w
            nose_px_y = landmarks[1].y * img_h
            gaze_vector = self._compute_gaze_projection(adj_yaw, adj_pitch, nose_px_x, nose_px_y, img_w, img_h)

            # Compact key landmarks for client visualization
            key_landmarks = self._extract_key_landmarks(landmarks, img_w, img_h)

        # --- 2. Mobile Phone Detection (Ultralytics YOLO) ---
        # Run YOLO on every received frame (flow-controlled by client, so no need to skip)
        should_run_yolo = True
        
        if should_run_yolo:
            # Resize frame to 320px for ultra-fast YOLO inference, then scale boxes back up
            yolo_h, yolo_w = frame_bgr.shape[:2]
            yolo_target = 320
            scale_x = yolo_w / yolo_target if yolo_w > yolo_target else 1.0
            scale_y = yolo_h / yolo_target if yolo_h > yolo_target else 1.0
            if yolo_w > yolo_target:
                small = cv2.resize(frame_bgr, (yolo_target, int(yolo_h * yolo_target / yolo_w)))
            else:
                small = frame_bgr
                scale_x = 1.0
                scale_y = 1.0

            yolo_res = self.yolo_model(small, classes=[67], conf=phone_cutoff, verbose=False, imgsz=yolo_target)
            boxes = []
            max_conf = 0.0

            if len(yolo_res) > 0 and len(yolo_res[0].boxes) > 0:
                small_h, small_w = small.shape[:2]
                for b in yolo_res[0].boxes:
                    xyxy = b.xyxy[0].cpu().numpy().tolist()
                    conf = float(b.conf[0].cpu().numpy())
                    if conf > max_conf:
                        max_conf = conf
                    # Normalized [0..1] coordinates for resolution-independent overlay
                    nx1 = max(0.0, min(1.0, float(xyxy[0]) / max(1, small_w)))
                    ny1 = max(0.0, min(1.0, float(xyxy[1]) / max(1, small_h)))
                    nx2 = max(0.0, min(1.0, float(xyxy[2]) / max(1, small_w)))
                    ny2 = max(0.0, min(1.0, float(xyxy[3]) / max(1, small_h)))

                    # Scale boxes back to original frame size
                    x1 = round(nx1 * img_w, 1)
                    y1 = round(ny1 * img_h, 1)
                    x2 = round(nx2 * img_w, 1)
                    y2 = round(ny2 * img_h, 1)
                    boxes.append({
                        "bbox": [x1, y1, x2, y2],
                        "norm_bbox": [round(nx1, 4), round(ny1, 4), round(nx2, 4), round(ny2, 4)],
                        "confidence": round(conf, 3),
                        "class": "cell phone"
                    })
            
            self.last_phone_boxes = boxes
            self.last_phone_detected = len(boxes) > 0
            self.last_phone_max_conf = round(max_conf, 3)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        return {
            "face_detected": face_detected,
            "left_ear": round(left_ear, 3),
            "right_ear": round(right_ear, 3),
            "avg_ear": round(avg_ear, 3),
            "eyes_closed": eyes_closed,
            "mar": round(mar, 3),
            "mouth_area": round(mouth_area, 1),
            "mouth_wide_open": mouth_wide_open,
            "head_yaw": round(adj_yaw, 1),
            "head_pitch": round(adj_pitch, 1),
            "head_roll": round(raw_roll, 1),
            "head_turned": head_turned,
            "phone_detected": self.last_phone_detected,
            "phone_boxes": self.last_phone_boxes,
            "phone_max_confidence": self.last_phone_max_conf,
            "gaze_vector": gaze_vector,
            "key_landmarks": key_landmarks,
            "inference_time_ms": elapsed_ms
        }
