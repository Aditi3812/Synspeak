"""
Penalty Score Manager — 100-point discipline scoring system.
Tracks deductions per confirmed distraction event and rewards focus streaks.
"""
import time
from typing import List, Dict, Any, Optional

DEFAULT_PENALTIES = {
    "drowsy": 5,
    "gaze": 3,
    "absence": 5,
    "phone": 10,
    "yawn": 2,
    "other": 3,
}
REPEATED_PHONE_BONUS = 5
RAPID_FIRE_BONUS = 5  # 3+ events in 5 min


class PenaltyManager:
    def __init__(self, penalty_table=None, reward_interval_s=900.0, reward_points=5):
        self.penalty_table = penalty_table or dict(DEFAULT_PENALTIES)
        self.reward_interval_s = reward_interval_s
        self.reward_points = reward_points
        self._score = 100.0
        self._total_deducted = 0
        self._total_rewarded = 0
        self.penalty_history: List[Dict[str, Any]] = []
        self.reward_history: List[Dict[str, Any]] = []
        self._penalised_ids: set = set()
        self._recent_event_times: List[float] = []
        self.focus_streak_seconds = 0.0
        self.longest_streak_seconds = 0.0
        self.total_qualified_focus_seconds = 0.0
        self._focus_streak_active = False
        self._last_reward_perf: Optional[float] = None

    @property
    def score(self):
        return max(0, min(100, int(round(self._score))))

    @property
    def total_deducted(self):
        return self._total_deducted

    @property
    def total_rewarded(self):
        return self._total_rewarded

    def apply_penalty(self, event_id, category, reason, wall_time_str, is_repeated_phone=False):
        if event_id in self._penalised_ids:
            return {"deducted": 0, "already_counted": True}
        self._penalised_ids.add(event_id)
        base = self.penalty_table.get(category, DEFAULT_PENALTIES["other"])
        bonus = 0
        if category == "phone" and is_repeated_phone:
            bonus += REPEATED_PHONE_BONUS
        now = time.perf_counter()
        self._recent_event_times.append(now)
        cutoff = now - 300.0
        self._recent_event_times = [t for t in self._recent_event_times if t >= cutoff]
        if len(self._recent_event_times) >= 3:
            bonus += RAPID_FIRE_BONUS
        total = base + bonus
        self._score = max(0.0, self._score - total)
        self._total_deducted += total
        entry = {
            "event_id": event_id,
            "category": category,
            "reason": reason,
            "base_deduction": base,
            "bonus_deduction": bonus,
            "total_deduction": total,
            "score_after": self.score,
            "timestamp": wall_time_str,
        }
        self.penalty_history.append(entry)
        return {"deducted": total, "already_counted": False, "entry": entry}

    def update_focus_streak(self, is_focused, dt, wall_time_str):
        """Returns reward dict if streak reward earned, else None."""
        if is_focused:
            if not self._focus_streak_active:
                self._focus_streak_active = True
                self._last_reward_perf = time.perf_counter()
            self.focus_streak_seconds += dt
            self.total_qualified_focus_seconds += dt
            if self.focus_streak_seconds > self.longest_streak_seconds:
                self.longest_streak_seconds = self.focus_streak_seconds
            if self._last_reward_perf is not None:
                elapsed = time.perf_counter() - self._last_reward_perf
                if elapsed >= self.reward_interval_s:
                    return self._grant_reward(wall_time_str)
        else:
            self.focus_streak_seconds = 0.0
            self._focus_streak_active = False
            self._last_reward_perf = None
        return None

    def reset(self):
        self._score = 100.0
        self._total_deducted = 0
        self._total_rewarded = 0
        self.penalty_history.clear()
        self.reward_history.clear()
        self._penalised_ids.clear()
        self._recent_event_times.clear()
        self.focus_streak_seconds = 0.0
        self.longest_streak_seconds = 0.0
        self.total_qualified_focus_seconds = 0.0
        self._focus_streak_active = False
        self._last_reward_perf = None

    def get_summary(self):
        return {
            "score": self.score,
            "total_deducted": self._total_deducted,
            "total_rewarded": self._total_rewarded,
            "focus_streak_seconds": round(self.focus_streak_seconds, 1),
            "longest_streak_seconds": round(self.longest_streak_seconds, 1),
            "total_qualified_focus_seconds": round(self.total_qualified_focus_seconds, 1),
            "penalty_history": self.penalty_history[-20:],
            "reward_history": self.reward_history[-10:],
        }

    def _grant_reward(self, wall_time_str):
        pts = min(self.reward_points, 100 - self.score)
        self._score = min(100.0, self._score + pts)
        self._total_rewarded += pts
        self._last_reward_perf = time.perf_counter()
        entry = {
            "reward_points": pts,
            "score_after": self.score,
            "timestamp": wall_time_str,
            "streak_seconds": round(self.focus_streak_seconds, 1),
        }
        self.reward_history.append(entry)
        return entry
