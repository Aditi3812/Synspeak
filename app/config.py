import os
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")

class Settings(BaseModel):
    # Model Paths
    face_landmarker_path: str = os.path.join(MODELS_DIR, "face_landmarker.task")
    # Upgrade to YOLO11n for significantly enhanced phone detection
    yolo_model_path: str = os.path.join(MODELS_DIR, "yolo11n.pt") if os.path.exists(os.path.join(MODELS_DIR, "yolo11n.pt")) else os.path.join(MODELS_DIR, "yolov8n.pt")
    
    # Behavioural Estimation Thresholds
    ear_threshold: float = Field(0.21, description="Eye Aspect Ratio threshold below which eyes appear closed")
    head_yaw_threshold: float = Field(22.0, description="Degrees of yaw (left/right) beyond which head is turned away")
    head_pitch_threshold: float = Field(28.0, description="Degrees of pitch (up/down) beyond which head is tilted away")
    head_roll_threshold: float = Field(25.0, description="Degrees of roll (tilt) beyond which head is tilted")
    
    # Yawn Detection Thresholds
    mar_threshold: float = Field(0.50, description="Mouth Aspect Ratio (MAR) threshold indicating wide mouth opening")
    yawn_duration_threshold: float = Field(1.0, description="Duration in seconds of wide mouth opening before flagging a yawn")

    # Duration Thresholds (in seconds)
    drowsy_duration_threshold: float = Field(5.0, description="Duration in seconds of closed eyes before flagging drowsiness")
    gaze_duration_threshold: float = Field(5.0, description="Duration in seconds of looking away before flagging distraction")
    absence_duration_threshold: float = Field(30.0, description="Duration in seconds of absent face before flagging absence")
    phone_duration_threshold: float = Field(3.0, description="Duration in seconds of phone visibility before flagging distraction")
    
    # Enhanced Phone Detector Settings
    # 0.25 confidence threshold allows capturing phones in varied lighting, with covers, or held in hands
    phone_confidence_threshold: float = Field(0.25, description="YOLO confidence score cutoff for cell phone class (67)")
    phone_detection_interval: int = Field(2, description="Run YOLO inference every 2 frames for fast detection")
    
    # 5-Flag Alert System Rules (legacy recovery — now superseded by FlagManager)
    max_flags_before_alert: int = Field(5, description="Trigger punishment after N distraction flags")
    recovery_duration_seconds: float = Field(300.0, description="5-min recovery window (seconds)")
    max_flags_during_recovery: int = Field(1, description="Max flags allowed during recovery/punishment")

    # Punishment (One-Flag Challenge) Settings
    punishment_duration_seconds: float = Field(300.0, description="Punishment study period duration (default 5 min)")
    punishment_max_flags: int = Field(1, description="Max flags allowed before punishment timer resets")
    flag_window_seconds: float = Field(900.0, description="Rolling window for flag escalation (default 15 min)")

    # Penalty Score Settings
    penalty_drowsy: int = Field(5, description="Points deducted for prolonged eye closure")
    penalty_gaze: int = Field(3, description="Points deducted for sustained head turning")
    penalty_absence: int = Field(5, description="Points deducted for prolonged face absence")
    penalty_phone: int = Field(10, description="Points deducted for phone detection")
    penalty_yawn: int = Field(2, description="Points deducted for yawn")
    penalty_other: int = Field(3, description="Points deducted for other distractions")

    # Focus Reward Settings
    focus_reward_interval_seconds: float = Field(900.0, description="Focus duration to earn +5 points (default 15 min)")
    focus_reward_points: int = Field(5, description="Points awarded per focus streak reward")

    # Mouth mesh area (pixel count) threshold for yawn detection
    mouth_area_threshold: float = Field(1500.0, description="Pixel area of mouth polygon that indicates a yawn")

    # Server / Session defaults
    host: str = "0.0.0.0"
    port: int = 8000
    fps_target: int = 15

    # Core Engineering & Ethical Disclaimer
    ethical_disclaimer: str = (
        "Important Engineering & Behavioural Notice: "
        "Observable webcam indicators (facial orientation, eye openness, yawning, object proximity, presence) "
        "are behavioural estimates and do not directly measure cognitive focus or internal mental state. "
        "A student may close their eyes to contemplate, yawn due to low room oxygen or fatigue, look away to read handwritten notes, or glance at a phone for time. "
        "All metrics must be interpreted as observable behavioural proxies, not definitive cognitive focus."
    )

settings = Settings()
