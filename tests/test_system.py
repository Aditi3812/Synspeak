import os
import cv2
import numpy as np
import pytest
from app.config import settings
from app.detector import VisionDetector
from app.session_tracker import SessionTracker, StudyState, SessionStatus
from app.report_generator import ReportGenerator, format_duration

def test_format_duration():
    assert format_duration(45) == "00m 45s"
    assert format_duration(125) == "02m 05s"
    assert format_duration(3665) == "01h 01m 05s"

def test_vision_detector_face_and_pose():
    detector = VisionDetector()
    img_path = "models/test_face.jpg"
    assert os.path.exists(img_path), "Test face image must exist"
    
    img = cv2.imread(img_path)
    res = detector.process_frame(img)
    
    assert res["face_detected"] is True
    assert res["left_ear"] > 0.1
    assert res["right_ear"] > 0.1
    assert res["avg_ear"] > 0.1
    assert isinstance(res["head_yaw"], float)
    assert isinstance(res["head_pitch"], float)
    assert isinstance(res["head_roll"], float)
    assert res["gaze_vector"] is not None
    assert "origin" in res["gaze_vector"]
    assert "target" in res["gaze_vector"]

def test_vision_detector_absence():
    detector = VisionDetector()
    # Blank black image has no face
    black_img = np.zeros((480, 640, 3), dtype=np.uint8)
    res = detector.process_frame(black_img)
    
    assert res["face_detected"] is False
    assert res["avg_ear"] == 0.0
    assert res["head_turned"] is False

def test_session_tracker_workflow():
    tracker = SessionTracker()
    tracker.settings.drowsy_duration_threshold = 1.2
    tracker.settings.phone_duration_threshold = 0.5
    tracker.start_session(goal_minutes=25)
    assert tracker.status == SessionStatus.RUNNING
    
    # 1. Simulate 5 frames of focused study (dt=0.1s each -> 0.5s)
    focused_det = {
        "face_detected": True,
        "eyes_closed": False,
        "head_turned": False,
        "phone_detected": False,
        "avg_ear": 0.32,
        "head_yaw": 2.0,
        "head_pitch": 1.0,
        "dt": 0.1
    }
    for _ in range(5):
        summary = tracker.update(focused_det)
        
    assert tracker.focused_seconds > 0.3
    assert tracker.current_state == StudyState.FOCUSED
    assert tracker.concentration_percentage == 100.0

    # 2. Simulate brief blink (3 frames = 0.3s) - should NOT trigger drowsiness
    blink_det = dict(focused_det)
    blink_det["eyes_closed"] = True
    blink_det["avg_ear"] = 0.12
    for _ in range(3):
        tracker.update(blink_det)
    # Should still be focused because blink was < 1.2s threshold
    assert tracker.current_state == StudyState.FOCUSED

    # 3. Simulate prolonged eye closure (18 frames = 1.8s) - SHOULD trigger drowsiness
    for _ in range(18):
        tracker.update(blink_det)
    assert tracker.current_state == StudyState.DISTRACTED_DROWSY
    assert tracker.drowsy_distracted_seconds > 0.5

    # 4. Simulate return to focus
    for _ in range(5):
        tracker.update(focused_det)
    assert tracker.current_state == StudyState.FOCUSED
    # An event should have been logged
    assert len(tracker.distraction_events) >= 1
    assert tracker.distraction_events[0]["category"] == "drowsy"

    # 5. Simulate phone detection
    phone_det = dict(focused_det)
    phone_det["phone_detected"] = True
    phone_det["phone_max_confidence"] = 0.88
    for _ in range(10):
        tracker.update(phone_det)
    assert tracker.current_state == StudyState.DISTRACTED_PHONE
    assert tracker.phone_distracted_seconds > 0.5

    # 6. Stop session and test report generation
    tracker.stop_session()
    assert tracker.status == SessionStatus.COMPLETED
    
    report = ReportGenerator.generate_report(tracker)
    assert "session_id" in report
    assert "percentages" in report
    assert "concentration_score" in report["percentages"]
    assert report["percentages"]["concentration_score"] < 100.0
    assert "distraction_breakdown" in report
    assert report["distraction_breakdown"]["phone"]["seconds"] > 0
    assert "engineering_and_ethical_disclaimer" in report
    assert len(report["engineering_and_ethical_disclaimer"]["principles"]) >= 5
    assert len(report["insights"]) >= 1
