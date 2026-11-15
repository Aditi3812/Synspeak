"""
SessionTracker — Central orchestrator for the Synspeak AI Study Monitor.

Integrates:
  - Behavioral state machine (focused / distracted / absent)
  - FlagManager (rolling 15-min escalation, 5-flag punishment trigger)
  - PunishmentManager (One-Flag Challenge countdown)
  - PomodoroTimer (reliable monotonic Pomodoro countdown)
  - PenaltyManager (100-point discipline score + focus rewards)
"""
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

from app.config import Settings, settings as default_settings
from app.flag_manager import FlagManager
from app.punishment_manager import PunishmentManager
from app.penalty_manager import PenaltyManager
from app.pomodoro_timer import PomodoroTimer, PomodoroState


class StudyState(str, Enum):
    FOCUSED = "FOCUSED"
    DISTRACTED_PHONE = "DISTRACTED_PHONE"
    DISTRACTED_GAZE = "DISTRACTED_GAZE"
    DISTRACTED_DROWSY = "DISTRACTED_DROWSY"
    DISTRACTED_YAWN = "DISTRACTED_YAWN"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class SessionStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PUNISHMENT = "PUNISHMENT"
    COMPLETED = "COMPLETED"


class SessionTracker:
    """
    Main session orchestrator. Call update(detection_res) each frame.
    """

    def __init__(self, custom_settings: Settings = None):
        self.settings = custom_settings or default_settings

        # Sub-managers
        self.flag_mgr = FlagManager(
            max_flags=self.settings.max_flags_before_alert,
            window_seconds=self.settings.flag_window_seconds,
        )
        self.punishment_mgr = PunishmentManager(
            duration_seconds=self.settings.punishment_duration_seconds,
            max_flags_allowed=self.settings.punishment_max_flags,
        )
        self.penalty_mgr = PenaltyManager(
            penalty_table={
                "drowsy":   self.settings.penalty_drowsy,
                "gaze":     self.settings.penalty_gaze,
                "absence":  self.settings.penalty_absence,
                "phone":    self.settings.penalty_phone,
                "yawn":     self.settings.penalty_yawn,
                "other":    self.settings.penalty_other,
            },
            reward_interval_s=self.settings.focus_reward_interval_seconds,
            reward_points=self.settings.focus_reward_points,
        )
        self.pomodoro = PomodoroTimer()

        # Session lifecycle
        self.status: SessionStatus = SessionStatus.IDLE
        self.start_timestamp: Optional[datetime] = None
        self.end_timestamp: Optional[datetime] = None
        self.goal_minutes: Optional[int] = None

        # Time accruals (seconds)
        self.focused_seconds: float = 0.0
        self.phone_distracted_seconds: float = 0.0
        self.gaze_distracted_seconds: float = 0.0
        self.drowsy_distracted_seconds: float = 0.0
        self.yawn_distracted_seconds: float = 0.0
        self.absent_seconds: float = 0.0
        self.unknown_seconds: float = 0.0

        # Behavioral state
        self.current_state: StudyState = StudyState.UNKNOWN
        self.state_since_perf: float = time.perf_counter()
        self.last_frame_perf: Optional[float] = None

        # Temporal smoothing accumulators
        self.eyes_closed_accum_s: float = 0.0
        self.gaze_turned_accum_s: float = 0.0
        self.absence_accum_s: float = 0.0
        self.phone_accum_s: float = 0.0
        self.yawn_accum_s: float = 0.0

        # Distraction event recording
        self.distraction_events: List[Dict[str, Any]] = []
        self.current_active_event: Optional[Dict[str, Any]] = None
        self.event_counter: int = 0

        # Notification queue (read by main.py and forwarded to client)
        self.pending_notifications: List[Dict[str, Any]] = []

        # Timeline
        self.timeline_samples: List[Dict[str, Any]] = []
        self.last_sample_perf: float = 0.0

        # Signals for client
        self.alert_just_cleared: bool = False
        self._last_phone_event_time: float = 0.0  # for repeated phone detection
        self._last_phone_warning_time: float = 0.0  # for immediate phone warning on screen

    # ------------------------------------------------------------------ #
    # Session Lifecycle                                                    #
    # ------------------------------------------------------------------ #

    def start_session(self, goal_minutes: Optional[int] = None, total_laps: int = 1, break_minutes: int = 5):
        self.status = SessionStatus.RUNNING
        self.start_timestamp = datetime.now()
        self.end_timestamp = None
        self.goal_minutes = goal_minutes

        self.focused_seconds = 0.0
        self.phone_distracted_seconds = 0.0
        self.gaze_distracted_seconds = 0.0
        self.drowsy_distracted_seconds = 0.0
        self.yawn_distracted_seconds = 0.0
        self.absent_seconds = 0.0
        self.unknown_seconds = 0.0

        self.distraction_events = []
        self.current_active_event = None
        self.event_counter = 0
        self.timeline_samples = []
        self.pending_notifications = []
        self.alert_just_cleared = False
        self._last_phone_event_time = 0.0
        self._last_phone_warning_time = 0.0

        self.flag_mgr.reset_session()
        self.punishment_mgr.reset_full()
        self.penalty_mgr.reset()

        if goal_minutes and goal_minutes > 0:
            self.pomodoro.start(duration_minutes=goal_minutes, total_laps=total_laps, break_minutes=break_minutes)
        else:
            self.pomodoro.reset()

        now = time.perf_counter()
        self.state_since_perf = now
        self.last_frame_perf = now
        self.last_sample_perf = now
        self.current_state = StudyState.UNKNOWN

        self.eyes_closed_accum_s = 0.0
        self.gaze_turned_accum_s = 0.0
        self.absence_accum_s = 0.0
        self.phone_accum_s = 0.0
        self.yawn_accum_s = 0.0

    def pause_session(self):
        if self.status == SessionStatus.RUNNING:
            self._close_active_distraction_event()
            self.status = SessionStatus.PAUSED
            self.pomodoro.pause()
            self.last_frame_perf = None

    def resume_session(self):
        if self.status in (SessionStatus.PAUSED,):
            self.status = SessionStatus.RUNNING
            self.pomodoro.resume()
            now = time.perf_counter()
            self.last_frame_perf = now
            self.state_since_perf = now

    def stop_session(self):
        if self.status in (SessionStatus.RUNNING, SessionStatus.PAUSED, SessionStatus.PUNISHMENT):
            self._close_active_distraction_event()
            self.status = SessionStatus.COMPLETED
            self.end_timestamp = datetime.now()
            self.pomodoro.stop()

    def reset_session(self):
        self.status = SessionStatus.IDLE
        self.start_timestamp = None
        self.end_timestamp = None
        self.goal_minutes = None
        self.focused_seconds = 0.0
        self.phone_distracted_seconds = 0.0
        self.gaze_distracted_seconds = 0.0
        self.drowsy_distracted_seconds = 0.0
        self.yawn_distracted_seconds = 0.0
        self.absent_seconds = 0.0
        self.unknown_seconds = 0.0
        self.distraction_events = []
        self.current_active_event = None
        self.timeline_samples = []
        self.pending_notifications = []
        self.current_state = StudyState.UNKNOWN
        self.alert_just_cleared = False
        self._last_phone_warning_time = 0.0
        self.flag_mgr.reset_session()
        self.punishment_mgr.reset_full()
        self.penalty_mgr.reset()
        self.pomodoro.reset()

    # ------------------------------------------------------------------ #
    # Main Update (called every frame)                                     #
    # ------------------------------------------------------------------ #

    def update(self, detection_res: Dict[str, Any]) -> Dict[str, Any]:
        now = time.perf_counter()
        wall_time_str = datetime.now().strftime("%H:%M:%S")

        # Delta time calculation
        if "dt" in detection_res and detection_res["dt"] is not None:
            dt = detection_res["dt"]
        elif self.last_frame_perf is None:
            dt = 0.05
        else:
            dt = min(1.0, max(0.001, now - self.last_frame_perf))
        self.last_frame_perf = now
        detection_res["dt"] = dt

        # Determine behavioral state
        new_state = self._determine_instant_state(detection_res)

        # Tick Pomodoro (only if running or on break, and NOT in punishment)
        if self.status == SessionStatus.RUNNING and not self.punishment_mgr.is_active:
            pom_result = self.pomodoro.tick()
            if pom_result == "completed":
                self.status = SessionStatus.COMPLETED
                self._push_notification({
                    "type": "pomodoro_completed",
                    "title": "🎉 Study Session Complete!",
                    "message": f"Congratulations! You've completed all {self.pomodoro.total_laps} study laps!",
                    "severity": "success",
                    "audio": "session_bell",
                })
            elif pom_result == "break_started":
                if self.current_active_event is not None:
                    self._close_active_distraction_event(wall_time_str)
                self._push_notification({
                    "type": "break_started",
                    "title": "☕ Break Time!",
                    "message": f"Lap {self.pomodoro.current_lap} complete! Enjoy your {self.pomodoro.break_duration_minutes}m break. Monitoring is paused.",
                    "severity": "info",
                    "audio": "session_bell",
                })
            elif pom_result == "lap_started":
                self._push_notification({
                    "type": "lap_started",
                    "title": "🎯 Break Finished!",
                    "message": f"Lap {self.pomodoro.current_lap} of {self.pomodoro.total_laps} starts now. Stay focused!",
                    "severity": "info",
                    "audio": "gentle_chime",
                })

        # Break Mode: in break time, NO events or penalties are flagged
        if self.pomodoro.is_break:
            self.eyes_closed_accum_s = 0.0
            self.gaze_turned_accum_s = 0.0
            self.absence_accum_s = 0.0
            self.phone_accum_s = 0.0
            self.yawn_accum_s = 0.0
            new_state = StudyState.FOCUSED

        # Monitoring OK: face is visible (or we have known state data)
        monitoring_ok = detection_res.get("face_detected", False)

        # Tick punishment timer
        if self.punishment_mgr.is_active:
            p_result = self.punishment_mgr.tick(monitoring_ok)
            if p_result == "completed":
                self._on_punishment_completed(wall_time_str)

        # Only accrue session metrics if running or in punishment
        is_session_active = self.status in (SessionStatus.RUNNING, SessionStatus.PUNISHMENT)

        if is_session_active:
            # Accrue time (during break, do not accrue to study distraction)
            if self.pomodoro.is_break:
                pass  # Break time is exempt from distraction tracking
            elif new_state == StudyState.FOCUSED:
                self.focused_seconds += dt
            elif new_state == StudyState.DISTRACTED_PHONE:
                self.phone_distracted_seconds += dt
            elif new_state == StudyState.DISTRACTED_GAZE:
                self.gaze_distracted_seconds += dt
            elif new_state == StudyState.DISTRACTED_DROWSY:
                self.drowsy_distracted_seconds += dt
            elif new_state == StudyState.DISTRACTED_YAWN:
                self.yawn_distracted_seconds += dt
            elif new_state == StudyState.ABSENT:
                self.absent_seconds += dt
            else:
                self.unknown_seconds += dt

            # Immediate warning as soon as mobile phone appears on screen (only during active focus study, not during break)
            if not self.pomodoro.is_break and detection_res.get("phone_detected"):
                if now - self._last_phone_warning_time >= 10.0:
                    self._last_phone_warning_time = now
                    self._push_notification({
                        "type": "immediate_phone_warning",
                        "category": "phone",
                        "title": "📱 Phone Detected!",
                        "message": "Mobile phone visible! Put it away — a flag will be raised in 3 seconds.",
                        "severity": "warning",
                        "audio": "warning",
                    })

            is_distracted = (not self.pomodoro.is_break) and (new_state in (
                StudyState.DISTRACTED_PHONE,
                StudyState.DISTRACTED_GAZE,
                StudyState.DISTRACTED_DROWSY,
                StudyState.DISTRACTED_YAWN,
                StudyState.ABSENT,
            ))

            if is_distracted:
                if self.current_active_event is None:
                    # New distraction event
                    self.event_counter += 1
                    category = self._state_to_category(new_state)
                    reason = self._state_to_reason(new_state)

                    self.current_active_event = {
                        "id": self.event_counter,
                        "category": category,
                        "reason": reason,
                        "start_offset_s": round(self.total_elapsed_seconds, 1),
                        "start_time": wall_time_str,
                        "duration_s": 0.0,
                        "peak_detail": self._extract_peak_detail(new_state, detection_res),
                        "flag_id": None,
                        "penalty": 0,
                    }

                    # Push event-specific notification
                    from app.flag_manager import EVENT_MESSAGES
                    self._push_notification({
                        "type": "distraction_event",
                        "category": category,
                        "message": EVENT_MESSAGES.get(category, "Distraction detected."),
                        "severity": "warning",
                        "audio": "gentle_chime",
                    })

                else:
                    # Update duration of ongoing event
                    self.current_active_event["duration_s"] = round(
                        self.current_active_event["duration_s"] + dt, 1
                    )
                    # Priority upgrade if phone appears mid-event
                    if new_state == StudyState.DISTRACTED_PHONE and self.current_active_event["category"] != "phone":
                        self.current_active_event["category"] = "phone"
                        self.current_active_event["reason"] = "Mobile Phone Visible"

            else:
                # Focused or unknown — close any active distraction event
                if self.current_active_event is not None:
                    closed = self._close_active_distraction_event(wall_time_str)
                    if closed:
                        self._process_closed_event(closed, wall_time_str)

                # Update penalty focus streak
                is_truly_focused = (new_state == StudyState.FOCUSED)
                reward = self.penalty_mgr.update_focus_streak(is_truly_focused, dt, wall_time_str)
                if reward:
                    self._push_notification({
                        "type": "focus_reward",
                        "title": "Focus Reward!",
                        "message": f"Excellent work! +{reward['reward_points']} discipline points earned.",
                        "severity": "success",
                        "audio": "recovery_success",
                        "reward": reward,
                    })

            # Timeline sample (1/second)
            if now - self.last_sample_perf >= 1.0:
                self.last_sample_perf = now
                self.timeline_samples.append({
                    "t": round(self.total_elapsed_seconds, 1),
                    "state": new_state.value,
                    "ear": detection_res.get("avg_ear", 0.0),
                    "mar": detection_res.get("mar", 0.0),
                    "yaw": detection_res.get("head_yaw", 0.0),
                    "pitch": detection_res.get("head_pitch", 0.0),
                    "conc": round(self.concentration_percentage, 1),
                    "score": self.penalty_mgr.score,
                })
                if len(self.timeline_samples) > 3600:
                    self.timeline_samples = self.timeline_samples[-3600:]

        if new_state != self.current_state:
            self.current_state = new_state
            self.state_since_perf = now

        current_state_duration = round(now - self.state_since_perf, 1)

        # Consume punishment signals
        p_signals = self.punishment_mgr.consume_signals()

        summary = self.get_summary(current_state_duration)
        self.alert_just_cleared = False
        return summary

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _process_closed_event(self, event: Dict[str, Any], wall_time_str: str):
        """After a distraction event ends, raise flag + apply penalty."""
        event_id = event["id"]
        category = event["category"]
        reason = event["reason"]
        in_punishment = self.punishment_mgr.is_active

        # Raise flag
        flag = self.flag_mgr.try_raise_flag(event_id, category, reason, wall_time_str, in_punishment)
        if flag:
            event["flag_id"] = flag["flag_id"]

            # Push escalation notification
            self._push_notification({
                "type": "flag_escalation",
                "flag_id": flag["flag_id"],
                "escalation_level": flag["escalation_level"],
                "title": flag["escalation_title"],
                "message": flag["escalation_message"],
                "severity": flag["severity"],
                "audio": flag["audio_cue"],
            })

            # Check punishment trigger
            if self.flag_mgr.punishment_triggered and not self.punishment_mgr.is_active:
                frozen_remaining = self.pomodoro.remaining_seconds
                self.pomodoro.freeze()
                self.punishment_mgr.activate(frozen_remaining, wall_time_str)
                self.status = SessionStatus.PUNISHMENT
                self._push_notification({
                    "type": "punishment_activated",
                    "title": "ONE-FLAG CHALLENGE",
                    "message": "Discipline mode activated! Complete 5 minutes of focused study.",
                    "severity": "punishment",
                    "audio": "major_alert",
                    "frozen_pomodoro": frozen_remaining,
                })

            # Handle flag during punishment
            if in_punishment:
                was_reset = self.punishment_mgr.register_flag_during_punishment(event_id, wall_time_str)
                if was_reset:
                    self._push_notification({
                        "type": "punishment_reset",
                        "title": "Challenge Reset!",
                        "message": "Distraction detected during your challenge. Punishment timer restarted.",
                        "severity": "critical",
                        "audio": "critical",
                    })

        # Apply penalty score deduction
        is_repeated_phone = (category == "phone" and
                             (time.perf_counter() - self._last_phone_event_time) < 300)
        if category == "phone":
            self._last_phone_event_time = time.perf_counter()

        pen = self.penalty_mgr.apply_penalty(event_id, category, reason, wall_time_str, is_repeated_phone)
        event["penalty"] = pen.get("deducted", 0)

    def _on_punishment_completed(self, wall_time_str: str):
        """Called when punishment timer reaches zero successfully."""
        self.punishment_mgr.state  # already set to COMPLETED
        self.flag_mgr.reset_cycle()
        self.pomodoro.unfreeze()
        self.status = SessionStatus.RUNNING
        self.alert_just_cleared = True
        self._push_notification({
            "type": "punishment_completed",
            "title": "Challenge Completed!",
            "message": "Punishment completed! Your original Pomodoro session is resuming.",
            "severity": "success",
            "audio": "recovery_success",
        })

    def _push_notification(self, notification: Dict[str, Any]):
        notification["timestamp"] = datetime.now().strftime("%H:%M:%S")
        self.pending_notifications.append(notification)

    def _close_active_distraction_event(self, wall_time_str: str = None) -> Optional[Dict[str, Any]]:
        if not self.current_active_event:
            return None
        ev = self.current_active_event
        if ev["duration_s"] >= 0.5:
            ev["end_time"] = wall_time_str or datetime.now().strftime("%H:%M:%S")
            self.distraction_events.append(dict(ev))
            self.current_active_event = None
            return ev
        self.current_active_event = None
        return None

    def _determine_instant_state(self, det: Dict[str, Any]) -> StudyState:
        dt = det.get("dt", 0.05)

        # 1. Phone (highest priority)
        if det.get("phone_detected"):
            self.phone_accum_s += dt
            if self.phone_accum_s >= self.settings.phone_duration_threshold:
                return StudyState.DISTRACTED_PHONE
        else:
            self.phone_accum_s = max(0.0, self.phone_accum_s - dt * 2)

        # 2. Absence
        if not det.get("face_detected"):
            self.absence_accum_s += dt
            self.eyes_closed_accum_s = 0.0
            # If head was turned or turning away, keep accumulating gaze turned rather than wiping out
            if self.gaze_turned_accum_s > 0:
                self.gaze_turned_accum_s += dt
                if self.gaze_turned_accum_s >= self.settings.gaze_duration_threshold:
                    return StudyState.DISTRACTED_GAZE
            self.yawn_accum_s = 0.0
            if self.absence_accum_s >= self.settings.absence_duration_threshold:
                return StudyState.ABSENT
            return StudyState.UNKNOWN
        else:
            self.absence_accum_s = 0.0

        # 3. Eyes closed (drowsy)
        if det.get("eyes_closed"):
            self.eyes_closed_accum_s += dt
            if self.eyes_closed_accum_s >= self.settings.drowsy_duration_threshold:
                return StudyState.DISTRACTED_DROWSY
        else:
            self.eyes_closed_accum_s = 0.0

        # 4. Yawn (wide mouth open)
        if det.get("mouth_wide_open"):
            self.yawn_accum_s += dt
            if self.yawn_accum_s >= self.settings.yawn_duration_threshold:
                return StudyState.DISTRACTED_YAWN
        else:
            self.yawn_accum_s = max(0.0, self.yawn_accum_s - dt * 2)

        # 5. Head turned
        if det.get("head_turned"):
            self.gaze_turned_accum_s += dt
            if self.gaze_turned_accum_s >= self.settings.gaze_duration_threshold:
                return StudyState.DISTRACTED_GAZE
        else:
            self.gaze_turned_accum_s = max(0.0, self.gaze_turned_accum_s - dt)

        return StudyState.FOCUSED

    def _state_to_category(self, state: StudyState) -> str:
        mapping = {
            StudyState.DISTRACTED_PHONE: "phone",
            StudyState.DISTRACTED_GAZE: "gaze",
            StudyState.DISTRACTED_DROWSY: "drowsy",
            StudyState.DISTRACTED_YAWN: "yawn",
            StudyState.ABSENT: "absence",
        }
        return mapping.get(state, "other")

    def _state_to_reason(self, state: StudyState) -> str:
        mapping = {
            StudyState.DISTRACTED_PHONE: "Mobile Phone Visible",
            StudyState.DISTRACTED_GAZE: "Head Turned Away from Screen",
            StudyState.DISTRACTED_DROWSY: "Prolonged Eye Closure",
            StudyState.DISTRACTED_YAWN: "Yawning Observed (Fatigue Indicator)",
            StudyState.ABSENT: "Absent from Camera View",
        }
        return mapping.get(state, "Unclassified Inattention")

    def _extract_peak_detail(self, state: StudyState, det: Dict[str, Any]) -> str:
        if state == StudyState.DISTRACTED_PHONE:
            return f"Phone Confidence: {int(det.get('phone_max_confidence', 0) * 100)}%"
        if state == StudyState.DISTRACTED_GAZE:
            return f"Yaw: {det.get('head_yaw', 0)}°, Pitch: {det.get('head_pitch', 0)}°"
        if state == StudyState.DISTRACTED_DROWSY:
            return f"Avg EAR: {det.get('avg_ear', 0)}"
        if state == StudyState.DISTRACTED_YAWN:
            return f"MAR: {det.get('mar', 0)}"
        if state == StudyState.ABSENT:
            return "No face detected"
        return ""

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def total_distracted_seconds(self) -> float:
        return (self.phone_distracted_seconds + self.gaze_distracted_seconds +
                self.drowsy_distracted_seconds + self.yawn_distracted_seconds)

    @property
    def total_elapsed_seconds(self) -> float:
        return (self.focused_seconds + self.total_distracted_seconds +
                self.absent_seconds + self.unknown_seconds)

    @property
    def concentration_percentage(self) -> float:
        active = self.focused_seconds + self.total_distracted_seconds + self.absent_seconds
        if active < 0.5:
            return 100.0 if self.current_state == StudyState.FOCUSED else 0.0
        return round(min(100.0, max(0.0, (self.focused_seconds / active) * 100.0)), 1)

    # ------------------------------------------------------------------ #
    # Summary                                                              #
    # ------------------------------------------------------------------ #

    def get_summary(self, current_state_duration: float = 0.0) -> Dict[str, Any]:
        notifications = list(self.pending_notifications)
        self.pending_notifications.clear()

        return {
            # Session
            "session_status": self.status.value,
            "current_state": self.current_state.value,
            "current_state_duration_s": current_state_duration,
            "concentration_percentage": self.concentration_percentage,

            # Time accruals
            "focused_seconds": round(self.focused_seconds, 1),
            "distracted_seconds": round(self.total_distracted_seconds, 1),
            "phone_distracted_seconds": round(self.phone_distracted_seconds, 1),
            "gaze_distracted_seconds": round(self.gaze_distracted_seconds, 1),
            "drowsy_distracted_seconds": round(self.drowsy_distracted_seconds, 1),
            "yawn_distracted_seconds": round(self.yawn_distracted_seconds, 1),
            "absent_seconds": round(self.absent_seconds, 1),
            "unknown_seconds": round(self.unknown_seconds, 1),
            "total_elapsed_seconds": round(self.total_elapsed_seconds, 1),

            # Events
            "distraction_event_count": len(self.distraction_events) + (1 if self.current_active_event else 0),
            "recent_events": self.distraction_events[-5:],
            "active_event": self.current_active_event,

            # Flags
            "flags": self.flag_mgr.get_summary(),

            # Legacy fields (keep existing UI working)
            "flags_count": self.flag_mgr.total_flags,
            "active_flags": self.flag_mgr.cycle_flags,
            "max_flags_before_alert": self.settings.max_flags_before_alert,
            "major_alert_active": self.punishment_mgr.is_active,
            "recovery_seconds_remaining": self.punishment_mgr.remaining_seconds,
            "recovery_flags_incurred": self.punishment_mgr.punishment_flags,
            "max_flags_during_recovery": self.settings.punishment_max_flags,
            "alert_just_cleared": self.alert_just_cleared,

            # Punishment
            "punishment": self.punishment_mgr.get_summary(),

            # Pomodoro
            "pomodoro": self.pomodoro.get_summary(),

            # Penalty / Score
            "discipline": self.penalty_mgr.get_summary(),

            # Notifications (consumed each frame)
            "notifications": notifications,
        }
