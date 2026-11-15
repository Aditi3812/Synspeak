"""
Flag Manager — Rolling 15-minute distraction flag window with 5-flag escalation.
Manages flag lifecycle, escalation levels, and punishment trigger detection.

Rules:
- Each confirmed unique distraction event generates exactly ONE flag.
- Same continuous event cannot generate multiple flags.
- Flags older than 15 minutes (configurable) expire from the escalation counter.
- Expired flags remain in session history for reporting.
- After punishment completes, escalation counter resets for next cycle.
"""
import time
from datetime import datetime
from typing import List, Dict, Any, Optional


ESCALATION_MESSAGES = {
    1: {
        "title": "Distraction Detected",
        "message": "You've been distracted. Get back to studying.",
        "severity": "info",
        "audio": "gentle_chime",
    },
    2: {
        "title": "Second Distraction",
        "message": "Warning! This is your second distraction.",
        "severity": "warning",
        "audio": "warning",
    },
    3: {
        "title": "Final Warning",
        "message": "Final warning. Two more distractions will trigger punishment.",
        "severity": "warning",
        "audio": "warning",
    },
    4: {
        "title": "Critical Warning",
        "message": "One more distraction will activate punishment!",
        "severity": "critical",
        "audio": "critical",
    },
    5: {
        "title": "Punishment Activated",
        "message": "Discipline mode activated! Complete your additional 5-minute study challenge.",
        "severity": "punishment",
        "audio": "major_alert",
    },
}

EVENT_MESSAGES = {
    "drowsy": "Your eyes have been closed for too long. Stay alert and return to studying.",
    "gaze": "You're looking away from your study area. Bring your attention back.",
    "absence": "Your face is no longer visible. Please return to your study position.",
    "phone": "Mobile phone detected! Put it away and return to studying.",
    "yawn": "Yawning observed — you may be fatigued. Take a breath and refocus.",
    "other": "Distraction detected. Please refocus.",
}


class FlagManager:
    """
    Manages the rolling 15-minute distraction flag window and escalation.
    """

    def __init__(self, max_flags: int = 5, window_seconds: float = 900.0):
        self.max_flags = max_flags          # flags before punishment
        self.window_seconds = window_seconds  # rolling window (15 min)

        # All flags ever raised this session (for history/reporting)
        self.session_flags: List[Dict[str, Any]] = []

        # Flags within the current rolling window (by perf_counter timestamp)
        self._window_flag_times: List[float] = []  # perf_counter at flag raise

        # Current escalation cycle counter (resets after punishment completes)
        self.cycle_flags: int = 0

        # Lifetime flag count (never resets)
        self.total_flags: int = 0

        # Track which event_ids have already generated a flag
        self._flagged_event_ids: set = set()

        # Last notification to send
        self.pending_notification: Optional[Dict[str, Any]] = None

        # Whether punishment was triggered this cycle
        self.punishment_triggered: bool = False

        # Total punishments triggered session-wide
        self.total_punishments_triggered: int = 0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def try_raise_flag(self, event_id: int, category: str, reason: str,
                       wall_time_str: str, in_punishment: bool = False) -> Optional[Dict[str, Any]]:
        """
        Attempt to raise a flag for a confirmed distraction event.
        Returns flag dict (with escalation info) if a new flag was raised, else None.
        Guards: same event_id cannot raise more than one flag.
        """
        if event_id in self._flagged_event_ids:
            return None  # already flagged this event

        self._flagged_event_ids.add(event_id)
        self._expire_old_flags()

        now_perf = time.perf_counter()
        self._window_flag_times.append(now_perf)
        self.cycle_flags += 1
        self.total_flags += 1

        escalation_level = min(self.cycle_flags, self.max_flags)
        escalation = ESCALATION_MESSAGES.get(escalation_level, ESCALATION_MESSAGES[1])
        event_msg = EVENT_MESSAGES.get(category, EVENT_MESSAGES["other"])

        # Check punishment trigger before building the flag dict
        is_punishment_trigger = (self.cycle_flags >= self.max_flags and not self.punishment_triggered)
        if is_punishment_trigger:
            self.punishment_triggered = True
            self.total_punishments_triggered += 1

        flag = {
            "flag_id": self.total_flags,
            "event_id": event_id,
            "category": category,
            "reason": reason,
            "escalation_level": escalation_level,
            # Legacy keys (kept for backward compat)
            "escalation_title": escalation["title"],
            "escalation_message": escalation["message"],
            "event_message": event_msg,
            # New unified keys used by session_tracker notification handler
            "title": escalation["title"],
            "message": escalation["message"],
            "cycle_flags": self.cycle_flags,
            "total_flags": self.total_flags,
            "severity": escalation["severity"],
            "audio": escalation["audio"],
            "audio_cue": escalation["audio"],
            "in_punishment": in_punishment,
            "punishment_triggered": is_punishment_trigger,
            "timestamp": wall_time_str,
            "perf_time": now_perf,
        }
        self.session_flags.append(flag)
        self.pending_notification = flag

        return flag

    def consume_notification(self) -> Optional[Dict[str, Any]]:
        """Pop and return pending notification (if any)."""
        n = self.pending_notification
        self.pending_notification = None
        return n

    def reset_cycle(self):
        """
        Called when punishment completes successfully.
        Resets cycle counter for next escalation window.
        Does NOT reset session_flags (history preserved).
        """
        self.cycle_flags = 0
        self._window_flag_times.clear()
        self.punishment_triggered = False

    def reset_session(self):
        """Full reset at session start."""
        self.session_flags.clear()
        self._window_flag_times.clear()
        self._flagged_event_ids.clear()
        self.cycle_flags = 0
        self.total_flags = 0
        self.punishment_triggered = False
        self.total_punishments_triggered = 0
        self.pending_notification = None

    def get_window_flag_count(self) -> int:
        """Active flags in rolling window (after expiry check)."""
        self._expire_old_flags()
        return len(self._window_flag_times)

    def flags_until_punishment(self) -> int:
        return max(0, self.max_flags - self.cycle_flags)

    def get_summary(self) -> Dict[str, Any]:
        self._expire_old_flags()
        return {
            "total_flags": self.total_flags,
            "cycle_flags": self.cycle_flags,
            "window_flags": len(self._window_flag_times),
            "flags_until_punishment": self.flags_until_punishment(),
            "punishment_triggered": self.punishment_triggered,
            "total_punishments": self.total_punishments_triggered,
            "recent_flags": self.session_flags[-5:],
        }

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _expire_old_flags(self):
        cutoff = time.perf_counter() - self.window_seconds
        self._window_flag_times = [t for t in self._window_flag_times if t >= cutoff]
