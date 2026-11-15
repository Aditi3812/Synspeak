"""
Pomodoro Timer Manager — Reliable, monotonic countdown timer.

States: IDLE → RUNNING → PAUSED → PUNISHMENT_FROZEN → BREAK → COMPLETED

Key invariants:
- Uses perf_counter deltas (not setInterval counting) — immune to tab suspension.
- Exactly preserves remaining_seconds when paused or frozen.
- Punishment freezes the Pomodoro; resuming restores the exact frozen value.
- Only one timer advances at a time.
"""
import time
from typing import Optional, Dict, Any
from enum import Enum


class PomodoroState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FROZEN = "FROZEN"       # paused because punishment is active
    BREAK = "BREAK"
    COMPLETED = "COMPLETED"


class PomodoroTimer:
    """
    Monotonic Pomodoro countdown timer with multi-lap and break support.
    Call tick() every frame to advance; it returns:
      - "completed": when all laps are finished
      - "break_started": when a focus lap ends and a break begins
      - "lap_started": when a break ends and next focus lap begins
      - None: during normal countdown
    """

    def __init__(self, duration_minutes: int = 25, total_laps: int = 1, break_minutes: int = 5):
        self.lap_duration_minutes = duration_minutes
        self.lap_duration_seconds = duration_minutes * 60.0
        self.total_laps = max(1, total_laps)
        self.current_lap = 1
        self.break_duration_minutes = break_minutes
        self.break_duration_seconds = break_minutes * 60.0

        self.duration_minutes = duration_minutes
        self.duration_seconds = self.lap_duration_seconds
        self.state = PomodoroState.IDLE
        self._remaining: float = self.duration_seconds
        self._last_tick_perf: Optional[float] = None
        self.elapsed_seconds: float = 0.0
        self._just_completed: bool = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self, duration_minutes: Optional[int] = None, total_laps: Optional[int] = None, break_minutes: Optional[int] = None):
        if duration_minutes is not None:
            self.lap_duration_minutes = duration_minutes
            self.lap_duration_seconds = duration_minutes * 60.0
            self.duration_minutes = duration_minutes
            self.duration_seconds = duration_minutes * 60.0
        if total_laps is not None:
            self.total_laps = max(1, total_laps)
        if break_minutes is not None:
            self.break_duration_minutes = break_minutes
            self.break_duration_seconds = break_minutes * 60.0

        self.current_lap = 1
        self.duration_seconds = self.lap_duration_seconds
        self._remaining = self.lap_duration_seconds
        self.elapsed_seconds = 0.0
        self.state = PomodoroState.RUNNING
        self._last_tick_perf = time.perf_counter()
        self._just_completed = False

    def pause(self):
        if self.state in (PomodoroState.RUNNING, PomodoroState.BREAK):
            self._prev_state = self.state
            self.state = PomodoroState.PAUSED
            self._last_tick_perf = None

    def resume(self):
        if self.state == PomodoroState.PAUSED:
            self.state = getattr(self, "_prev_state", PomodoroState.RUNNING)
            self._last_tick_perf = time.perf_counter()

    def freeze(self):
        """Freeze timer during punishment (preserves exact remaining)."""
        if self.state == PomodoroState.RUNNING:
            self.state = PomodoroState.FROZEN
            self._last_tick_perf = None

    def unfreeze(self):
        """Resume from frozen state after punishment completes."""
        if self.state == PomodoroState.FROZEN:
            self.state = PomodoroState.RUNNING
            self._last_tick_perf = time.perf_counter()

    def stop(self):
        self.state = PomodoroState.COMPLETED
        self._last_tick_perf = None

    def reset(self):
        self.state = PomodoroState.IDLE
        self.current_lap = 1
        self.duration_seconds = self.lap_duration_seconds
        self._remaining = self.lap_duration_seconds
        self.elapsed_seconds = 0.0
        self._last_tick_perf = None
        self._just_completed = False

    # ------------------------------------------------------------------ #
    # Tick                                                                 #
    # ------------------------------------------------------------------ #

    def tick(self) -> Optional[str]:
        """
        Advance timer by real elapsed time.
        """
        if self.state not in (PomodoroState.RUNNING, PomodoroState.BREAK):
            return None

        now = time.perf_counter()
        if self._last_tick_perf is None:
            self._last_tick_perf = now
            return None

        dt = min(2.0, now - self._last_tick_perf)
        self._last_tick_perf = now
        self._remaining = max(0.0, self._remaining - dt)
        self.elapsed_seconds += dt

        if self._remaining <= 0.0:
            if self.state == PomodoroState.RUNNING:
                # Finished a focus lap
                if self.current_lap < self.total_laps:
                    # More laps remain — go to break if break>0, else start next lap immediately
                    if self.break_duration_minutes > 0:
                        self.state = PomodoroState.BREAK
                        self.duration_seconds = self.break_duration_seconds
                        self._remaining = self.break_duration_seconds
                        return "break_started"
                    else:
                        # No break — seamlessly jump to the next focus lap
                        self.current_lap += 1
                        self.duration_seconds = self.lap_duration_seconds
                        self._remaining = self.lap_duration_seconds
                        return "lap_started"
                else:
                    # All laps done
                    self.state = PomodoroState.COMPLETED
                    self._just_completed = True
                    return "completed"
            elif self.state == PomodoroState.BREAK:
                # Finished break — start next focus lap
                self.current_lap += 1
                self.state = PomodoroState.RUNNING
                self.duration_seconds = self.lap_duration_seconds
                self._remaining = self.lap_duration_seconds
                return "lap_started"

        return None

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def remaining_seconds(self) -> float:
        return round(self._remaining, 1)

    @property
    def is_break(self) -> bool:
        return self.state == PomodoroState.BREAK

    @property
    def progress_pct(self) -> float:
        if self.duration_seconds <= 0:
            return 100.0
        return round(100.0 * (1.0 - self._remaining / self.duration_seconds), 1)

    def consume_completed(self) -> bool:
        v = self._just_completed
        self._just_completed = False
        return v

    def get_summary(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "remaining_seconds": self.remaining_seconds,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "duration_seconds": self.duration_seconds,
            "progress_pct": self.progress_pct,
            "is_running": self.state == PomodoroState.RUNNING,
            "is_break": self.is_break,
            "is_frozen": self.state == PomodoroState.FROZEN,
            "is_completed": self.state == PomodoroState.COMPLETED,
            "current_lap": self.current_lap,
            "total_laps": self.total_laps,
            "lap_minutes": self.lap_duration_minutes,
            "break_minutes": self.break_duration_minutes,
        }
