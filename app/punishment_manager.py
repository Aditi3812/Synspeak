"""
Punishment Manager — ONE-FLAG CHALLENGE state machine.

Lifecycle:
  IDLE → (5th flag) → ACTIVE → (timer reaches 0, ≤1 flags) → COMPLETED → IDLE
                             → (2nd flag during punishment) → RESET → ACTIVE (timer reset)

Key invariants:
- Original Pomodoro remaining_seconds is FROZEN while punishment is ACTIVE.
- Punishment timer only advances while monitoring is active (face visible or face check passing).
- One continuous distraction event cannot trigger multiple resets.
- After completion, the original Pomodoro resumes from its frozen value.
"""
import time
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class PunishmentState(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class PunishmentManager:
    """
    Manages the One-Flag Challenge punishment period.
    """

    def __init__(self, duration_seconds: float = 300.0, max_flags_allowed: int = 1):
        self.duration_seconds = duration_seconds
        self.max_flags_allowed = max_flags_allowed

        self.state = PunishmentState.IDLE

        # Frozen Pomodoro remaining seconds at moment of punishment trigger
        self.frozen_pomodoro_remaining: Optional[float] = None

        # Punishment countdown
        self._remaining: float = duration_seconds
        self._last_tick_perf: Optional[float] = None

        # Flag tracking during punishment
        self.punishment_flags: int = 0
        self._flagged_event_ids_during_punishment: set = set()

        # Reset tracking
        self.reset_count: int = 0
        self.total_punishment_seconds_served: float = 0.0

        # History
        self.punishment_history: list = []

        # Signals (read once, then cleared)
        self._just_completed: bool = False
        self._just_reset: bool = False
        self._just_activated: bool = False

        # Timestamps
        self.activation_time: Optional[str] = None
        self.completion_time: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_active(self) -> bool:
        return self.state == PunishmentState.ACTIVE

    @property
    def remaining_seconds(self) -> float:
        return round(self._remaining, 1)

    @property
    def progress_pct(self) -> float:
        return round(100.0 * (1.0 - self._remaining / self.duration_seconds), 1)

    def activate(self, frozen_pomodoro_remaining: float, wall_time_str: str):
        """
        Activate punishment, freezing the Pomodoro at its current remaining time.
        No-op if already active.
        """
        if self.state == PunishmentState.ACTIVE:
            return
        self.state = PunishmentState.ACTIVE
        self.frozen_pomodoro_remaining = frozen_pomodoro_remaining
        self._remaining = self.duration_seconds
        self._last_tick_perf = time.perf_counter()
        self.punishment_flags = 0
        self._flagged_event_ids_during_punishment.clear()
        self.reset_count = 0
        self.activation_time = wall_time_str
        self.completion_time = None
        self._just_activated = True

    def tick(self, monitoring_ok: bool) -> Optional[str]:
        """
        Advance the punishment timer by real elapsed time.
        Only advances if monitoring is OK.
        Returns "completed" if punishment just finished, else None.
        """
        if self.state != PunishmentState.ACTIVE:
            return None

        now = time.perf_counter()
        if self._last_tick_perf is None:
            self._last_tick_perf = now
            return None

        dt = min(1.0, now - self._last_tick_perf)
        self._last_tick_perf = now

        if monitoring_ok:
            self._remaining = max(0.0, self._remaining - dt)
            self.total_punishment_seconds_served += dt

        if self._remaining <= 0.0:
            return self._complete()

        return None

    def register_flag_during_punishment(self, event_id: int, wall_time_str: str) -> bool:
        """
        Register a new distraction flag during punishment.
        Returns True if this causes a punishment reset (exceeded max_flags_allowed).
        One continuous event (same event_id) cannot trigger multiple resets.
        """
        if self.state != PunishmentState.ACTIVE:
            return False
        if event_id in self._flagged_event_ids_during_punishment:
            return False  # same continuous event, ignore

        self._flagged_event_ids_during_punishment.add(event_id)
        self.punishment_flags += 1

        if self.punishment_flags > self.max_flags_allowed:
            self._reset_timer(wall_time_str)
            return True
        return False

    def consume_signals(self) -> Dict[str, bool]:
        """Read and clear one-shot signals."""
        sig = {
            "just_activated": self._just_activated,
            "just_reset": self._just_reset,
            "just_completed": self._just_completed,
        }
        self._just_activated = False
        self._just_reset = False
        self._just_completed = False
        return sig

    def get_summary(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "is_active": self.is_active,
            "remaining_seconds": self.remaining_seconds,
            "duration_seconds": self.duration_seconds,
            "progress_pct": self.progress_pct,
            "frozen_pomodoro_remaining": self.frozen_pomodoro_remaining,
            "punishment_flags": self.punishment_flags,
            "max_flags_allowed": self.max_flags_allowed,
            "reset_count": self.reset_count,
            "total_punishment_seconds_served": round(self.total_punishment_seconds_served, 1),
            "activation_time": self.activation_time,
            "completion_time": self.completion_time,
            "punishment_history_count": len(self.punishment_history),
        }

    def reset_full(self):
        """Full reset at session start."""
        self.state = PunishmentState.IDLE
        self.frozen_pomodoro_remaining = None
        self._remaining = self.duration_seconds
        self._last_tick_perf = None
        self.punishment_flags = 0
        self._flagged_event_ids_during_punishment.clear()
        self.reset_count = 0
        self.total_punishment_seconds_served = 0.0
        self.punishment_history.clear()
        self._just_activated = False
        self._just_reset = False
        self._just_completed = False
        self.activation_time = None
        self.completion_time = None

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _reset_timer(self, wall_time_str: str):
        """Reset punishment countdown to full duration."""
        self._remaining = self.duration_seconds
        self.reset_count += 1
        self.punishment_flags = 0        # allow 1 more before next reset
        self._flagged_event_ids_during_punishment.clear()
        self._just_reset = True

    def _complete(self) -> str:
        self.state = PunishmentState.COMPLETED
        self.completion_time = datetime.now().strftime("%H:%M:%S")
        self.punishment_history.append({
            "activation_time": self.activation_time,
            "completion_time": self.completion_time,
            "resets": self.reset_count,
            "flags_incurred": self.punishment_flags,
            "seconds_served": round(self.total_punishment_seconds_served, 1),
        })
        self._just_completed = True
        return "completed"
