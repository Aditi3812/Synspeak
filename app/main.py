import os
import json
import base64
import logging
from typing import Optional, Dict, Any

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, Settings
from app.detector import VisionDetector
from app.session_tracker import SessionTracker, SessionStatus
from app.report_generator import ReportGenerator

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("synspeak")

app = FastAPI(
    title="Real-Time AI Study Concentration Monitoring System",
    description="Estimates observable study behaviours and potential distraction patterns using MediaPipe and YOLOv8.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global or active session instances
detector = VisionDetector(settings)
tracker = SessionTracker(settings)
latest_report: Optional[Dict[str, Any]] = None

# Static Files
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>Synspeak AI Concentration Monitor is loading...</h2>")

@app.get("/api/status")
async def get_status():
    return {
        "status": "online",
        "models": {
            "face_landmarker": "loaded",
            "yolov8n_phone": "loaded"
        },
        "session_status": tracker.status.value,
        "calibrated": detector.calibrated,
        "baseline": {
            "yaw": detector.baseline_yaw,
            "pitch": detector.baseline_pitch,
            "ear": detector.baseline_ear
        },
        "disclaimer": settings.ethical_disclaimer
    }

@app.get("/api/settings")
async def get_settings():
    return {
        "ear_threshold": settings.ear_threshold,
        "head_yaw_threshold": settings.head_yaw_threshold,
        "head_pitch_threshold": settings.head_pitch_threshold,
        "head_roll_threshold": settings.head_roll_threshold,
        "mar_threshold": settings.mar_threshold,
        "yawn_duration_threshold": settings.yawn_duration_threshold,
        "drowsy_duration_threshold": settings.drowsy_duration_threshold,
        "gaze_duration_threshold": settings.gaze_duration_threshold,
        "absence_duration_threshold": settings.absence_duration_threshold,
        "phone_confidence_threshold": settings.phone_confidence_threshold,
        "phone_detection_interval": settings.phone_detection_interval,
        "max_flags_before_alert": settings.max_flags_before_alert,
        "recovery_duration_seconds": settings.recovery_duration_seconds,
        "punishment_duration_seconds": settings.punishment_duration_seconds,
        "punishment_max_flags": settings.punishment_max_flags,
        "flag_window_seconds": settings.flag_window_seconds,
        "penalty_drowsy": settings.penalty_drowsy,
        "penalty_gaze": settings.penalty_gaze,
        "penalty_absence": settings.penalty_absence,
        "penalty_phone": settings.penalty_phone,
        "penalty_yawn": settings.penalty_yawn,
        "penalty_other": settings.penalty_other,
        "focus_reward_interval_seconds": settings.focus_reward_interval_seconds,
        "focus_reward_points": settings.focus_reward_points,
        "mouth_area_threshold": settings.mouth_area_threshold
    }

@app.post("/api/settings")
async def update_settings(new_cfg: Dict[str, Any]):
    for k, v in new_cfg.items():
        if hasattr(settings, k):
            setattr(settings, k, float(v) if isinstance(v, (int, float)) else v)
    # Propagate to active tracker sub-managers
    tracker.flag_mgr.max_flags = int(settings.max_flags_before_alert)
    tracker.flag_mgr.window_seconds = float(settings.flag_window_seconds)
    tracker.punishment_mgr.duration_seconds = float(settings.punishment_duration_seconds)
    tracker.punishment_mgr.max_flags_allowed = int(settings.punishment_max_flags)
    tracker.penalty_mgr.reward_interval_s = float(settings.focus_reward_interval_seconds)
    tracker.penalty_mgr.reward_points = int(settings.focus_reward_points)
    tracker.penalty_mgr.penalty_table.update({
        "drowsy": int(settings.penalty_drowsy),
        "gaze": int(settings.penalty_gaze),
        "absence": int(settings.penalty_absence),
        "phone": int(settings.penalty_phone),
        "yawn": int(settings.penalty_yawn),
        "other": int(settings.penalty_other)
    })
    return {"status": "updated", "settings": await get_settings()}

@app.get("/api/report/latest")
async def get_latest_report():
    global latest_report
    if latest_report is None:
        if tracker.status != SessionStatus.IDLE:
            return ReportGenerator.generate_report(tracker)
        raise HTTPException(status_code=404, detail="No session report generated yet.")
    return latest_report

@app.get("/api/export/report")
async def export_report_json():
    global latest_report
    rep = latest_report or ReportGenerator.generate_report(tracker)
    return JSONResponse(
        content=rep,
        headers={"Content-Disposition": f"attachment; filename={rep.get('session_id', 'report')}.json"}
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global latest_report
    await websocket.accept()
    logger.info("WebSocket client connected.")

    last_received_frame: Optional[np.ndarray] = None

    try:
        while True:
            # Receive either binary frame bytes or JSON text control
            message = await websocket.receive()
            
            if "bytes" in message and message["bytes"] is not None:
                # Fast binary JPEG frame
                raw_bytes = message["bytes"]
                frame = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                last_received_frame = frame
                
                # Process frame with detector
                detection_res = detector.process_frame(
                    frame,
                    ear_thresh=settings.ear_threshold,
                    yaw_thresh=settings.head_yaw_threshold,
                    pitch_thresh=settings.head_pitch_threshold,
                    phone_conf_thresh=settings.phone_confidence_threshold,
                    mar_thresh=settings.mar_threshold
                )
                
                # Update tracker
                session_summary = tracker.update(detection_res)
                
                # Send telemetry response
                response = {
                    "type": "telemetry",
                    "detection": detection_res,
                    "session": session_summary
                }
                await websocket.send_text(json.dumps(response))

            elif "text" in message and message["text"] is not None:
                try:
                    payload = json.loads(message["text"])
                except Exception:
                    continue
                
                msg_type = payload.get("type")

                if msg_type == "frame":
                    # Base64 encoded frame
                    data_url = payload.get("image", "")
                    if "," in data_url:
                        data_url = data_url.split(",")[1]
                    frame_bytes = base64.b64decode(data_url)
                    frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue
                    last_received_frame = frame

                    detection_res = detector.process_frame(
                        frame,
                        ear_thresh=settings.ear_threshold,
                        yaw_thresh=settings.head_yaw_threshold,
                        pitch_thresh=settings.head_pitch_threshold,
                        phone_conf_thresh=settings.phone_confidence_threshold,
                        mar_thresh=settings.mar_threshold
                    )
                    session_summary = tracker.update(detection_res)

                    response = {
                        "type": "telemetry",
                        "detection": detection_res,
                        "session": session_summary
                    }
                    await websocket.send_text(json.dumps(response))

                elif msg_type == "start":
                    lap_min = payload.get("lap_minutes") or payload.get("goal_minutes") or 25
                    total_laps = payload.get("total_laps") or 1
                    break_min = payload.get("break_minutes") if payload.get("break_minutes") is not None else 5
                    tracker.start_session(goal_minutes=lap_min, total_laps=total_laps, break_minutes=break_min)
                    logger.info(f"Study session started. Lap: {lap_min}m, Laps: {total_laps}, Break: {break_min}m")
                    await websocket.send_text(json.dumps({
                        "type": "session_state",
                        "status": tracker.status.value,
                        "message": f"Pomodoro started: {lap_min}m focus × {total_laps} laps ({break_min}m breaks)."
                    }))

                elif msg_type == "pause":
                    tracker.pause_session()
                    logger.info("Study session paused.")
                    await websocket.send_text(json.dumps({
                        "type": "session_state",
                        "status": tracker.status.value,
                        "message": "Session paused."
                    }))

                elif msg_type == "resume":
                    tracker.resume_session()
                    logger.info("Study session resumed.")
                    await websocket.send_text(json.dumps({
                        "type": "session_state",
                        "status": tracker.status.value,
                        "message": "Session resumed."
                    }))

                elif msg_type == "stop":
                    tracker.stop_session()
                    latest_report = ReportGenerator.generate_report(tracker)
                    logger.info("Study session completed. Final report generated.")
                    await websocket.send_text(json.dumps({
                        "type": "report",
                        "report": latest_report
                    }))

                elif msg_type == "reset":
                    tracker.reset_session()
                    latest_report = None
                    logger.info("Study session reset.")
                    await websocket.send_text(json.dumps({
                        "type": "session_state",
                        "status": tracker.status.value,
                        "message": "Session reset."
                    }))

                elif msg_type == "calibrate":
                    if last_received_frame is not None:
                        success, baseline = detector.calibrate_baseline(last_received_frame)
                        await websocket.send_text(json.dumps({
                            "type": "calibration_result",
                            "success": success,
                            "baseline": baseline
                        }))
                    else:
                        await websocket.send_text(json.dumps({
                            "type": "calibration_result",
                            "success": False,
                            "baseline": "No camera frame received yet to calibrate."
                        }))

                elif msg_type == "update_settings":
                    new_conf = payload.get("settings", {})
                    for k, v in new_conf.items():
                        if hasattr(settings, k):
                            setattr(settings, k, float(v) if isinstance(v, (int, float)) else v)
                    tracker.flag_mgr.max_flags = int(settings.max_flags_before_alert)
                    tracker.flag_mgr.window_seconds = float(settings.flag_window_seconds)
                    tracker.punishment_mgr.duration_seconds = float(settings.punishment_duration_seconds)
                    tracker.punishment_mgr.max_flags_allowed = int(settings.punishment_max_flags)
                    tracker.penalty_mgr.reward_interval_s = float(settings.focus_reward_interval_seconds)
                    tracker.penalty_mgr.reward_points = int(settings.focus_reward_points)
                    tracker.penalty_mgr.penalty_table.update({
                        "drowsy": int(settings.penalty_drowsy),
                        "gaze": int(settings.penalty_gaze),
                        "absence": int(settings.penalty_absence),
                        "phone": int(settings.penalty_phone),
                        "yawn": int(settings.penalty_yawn),
                        "other": int(settings.penalty_other)
                    })
                    await websocket.send_text(json.dumps({
                        "type": "settings_updated",
                        "settings": await get_settings()
                    }))

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
