import cv2
import json
import numpy as np
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_api_endpoints():
    # 1. Root HTML
    r = client.get("/")
    assert r.status_code == 200
    assert "Synspeak" in r.text

    # 2. Status
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "online"
    assert data["models"]["face_landmarker"] == "loaded"
    assert "disclaimer" in data

    # 3. Settings GET
    r = client.get("/api/settings")
    assert r.status_code == 200
    cfg = r.json()
    assert "ear_threshold" in cfg

    # 4. Settings POST
    r = client.post("/api/settings", json={"ear_threshold": 0.23})
    assert r.status_code == 200
    assert r.json()["settings"]["ear_threshold"] == 0.23

def test_websocket_flow():
    with client.websocket_connect("/ws") as ws:
        # 1. Start session
        ws.send_text(json.dumps({"type": "start", "goal_minutes": 20}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "session_state"
        assert msg["status"] == "RUNNING"

        # 2. Send JPEG frame bytes
        test_img = cv2.imread("models/test_face.jpg")
        _, buf = cv2.imencode(".jpg", test_img)
        ws.send_bytes(buf.tobytes())
        
        telemetry = json.loads(ws.receive_text())
        assert telemetry["type"] == "telemetry"
        assert "detection" in telemetry
        assert "session" in telemetry
        assert telemetry["detection"]["face_detected"] is True
        assert telemetry["session"]["session_status"] == "RUNNING"

        # 3. Stop session and get report
        ws.send_text(json.dumps({"type": "stop"}))
        report_msg = json.loads(ws.receive_text())
        assert report_msg["type"] == "report"
        assert "report" in report_msg
        assert "percentages" in report_msg["report"]
        assert "engineering_and_ethical_disclaimer" in report_msg["report"]
