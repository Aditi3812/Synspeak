import time
import pytest
from datetime import datetime

from app.config import Settings
from app.flag_manager import FlagManager
from app.penalty_manager import PenaltyManager
from app.punishment_manager import PunishmentManager, PunishmentState
from app.pomodoro_timer import PomodoroTimer, PomodoroState
from app.session_tracker import SessionTracker, SessionStatus, StudyState
from app.report_generator import ReportGenerator


def test_1_one_confirmed_distraction_generates_exactly_one_flag():
    flag_mgr = FlagManager(max_flags=5, window_seconds=900)
    flag1 = flag_mgr.try_raise_flag(event_id=1, category="phone", reason="Phone visible", wall_time_str="10:00:00")
    assert flag1 is not None
    assert flag_mgr.total_flags == 1
    assert flag_mgr.cycle_flags == 1

    # Attempting to raise flag again with same event_id must return None
    flag1_again = flag_mgr.try_raise_flag(event_id=1, category="phone", reason="Phone visible", wall_time_str="10:00:01")
    assert flag1_again is None
    assert flag_mgr.total_flags == 1
    assert flag_mgr.cycle_flags == 1


def test_2_five_flags_within_15_minutes_activate_exactly_one_punishment():
    flag_mgr = FlagManager(max_flags=5, window_seconds=900)
    for i in range(1, 5):
        f = flag_mgr.try_raise_flag(event_id=i, category="gaze", reason="Looking away", wall_time_str=f"10:0{i}:00")
        assert f is not None
        assert flag_mgr.punishment_triggered is False

    # 5th flag triggers punishment
    f5 = flag_mgr.try_raise_flag(event_id=5, category="phone", reason="Phone visible", wall_time_str="10:05:00")
    assert f5 is not None
    assert flag_mgr.punishment_triggered is True
    assert flag_mgr.total_punishments_triggered == 1

    # Extra flag after 5 does not increment total_punishments_triggered again in same cycle
    f6 = flag_mgr.try_raise_flag(event_id=6, category="drowsy", reason="Closed eyes", wall_time_str="10:06:00")
    assert flag_mgr.total_punishments_triggered == 1


def test_3_four_flags_do_not_activate_punishment():
    flag_mgr = FlagManager(max_flags=5, window_seconds=900)
    for i in range(1, 5):
        flag_mgr.try_raise_flag(event_id=i, category="yawn", reason="Yawn", wall_time_str=f"10:0{i}:00")
    assert flag_mgr.total_flags == 4
    assert flag_mgr.cycle_flags == 4
    assert flag_mgr.punishment_triggered is False
    assert flag_mgr.flags_until_punishment() == 1


def test_4_flags_older_than_15_minutes_expire_from_escalation_counter():
    # Use 0.2 second window for fast automated test
    flag_mgr = FlagManager(max_flags=5, window_seconds=0.2)
    flag_mgr.try_raise_flag(event_id=1, category="gaze", reason="Gaze", wall_time_str="10:00:00")
    assert flag_mgr.get_window_flag_count() == 1

    # Wait for window expiry
    time.sleep(0.3)
    assert flag_mgr.get_window_flag_count() == 0
    # Expired flags remain in session history for reporting
    assert len(flag_mgr.session_flags) == 1
    assert flag_mgr.session_flags[0]["event_id"] == 1


def test_5_original_pomodoro_pauses_at_exact_remaining_time():
    pom = PomodoroTimer(duration_minutes=25)
    pom.start()
    assert pom.state == PomodoroState.RUNNING
    initial_rem = pom.remaining_seconds

    # Fake a short passage of time
    time.sleep(0.1)
    pom.tick()
    rem_before_freeze = pom.remaining_seconds
    assert rem_before_freeze <= initial_rem

    # Freeze
    pom.freeze()
    assert pom.state == PomodoroState.FROZEN
    frozen_val = pom.remaining_seconds

    # While frozen, tick should do nothing
    time.sleep(0.1)
    pom.tick()
    assert pom.remaining_seconds == frozen_val


def test_6_punishment_timer_runs_independently():
    punish = PunishmentManager(duration_seconds=300, max_flags_allowed=1)
    punish.activate(frozen_pomodoro_remaining=1200.0, wall_time_str="10:00:00")
    assert punish.is_active is True
    assert punish.remaining_seconds == 300.0

    # Advance tick with monitoring_ok=True
    time.sleep(0.1)
    punish.tick(monitoring_ok=True)
    assert punish.remaining_seconds < 300.0
    assert punish.frozen_pomodoro_remaining == 1200.0


def test_7_new_distraction_during_punishment_resets_punishment_countdown():
    punish = PunishmentManager(duration_seconds=300, max_flags_allowed=1)
    punish.activate(frozen_pomodoro_remaining=1200.0, wall_time_str="10:00:00")

    time.sleep(0.1)
    punish.tick(monitoring_ok=True)
    assert punish.remaining_seconds < 300.0

    # First flag during punishment: allowed (max_flags_allowed=1)
    reset1 = punish.register_flag_during_punishment(event_id=101, wall_time_str="10:01:00")
    assert reset1 is False
    assert punish.punishment_flags == 1

    # Second flag during punishment: triggers reset to full 300s!
    reset2 = punish.register_flag_during_punishment(event_id=102, wall_time_str="10:02:00")
    assert reset2 is True
    assert punish.remaining_seconds == 300.0
    assert punish.reset_count == 1


def test_8_pomodoro_remains_frozen_throughout_punishment():
    tracker = SessionTracker()
    tracker.start_session(goal_minutes=25)
    pom_initial = tracker.pomodoro.remaining_seconds

    # Simulate punishment activation
    tracker.pomodoro.freeze()
    frozen_time = tracker.pomodoro.remaining_seconds

    tracker.punishment_mgr.activate(frozen_time, "10:00:00")
    tracker.status = SessionStatus.PUNISHMENT

    # Frame ticks in punishment mode
    for _ in range(5):
        time.sleep(0.02)
        tracker.update({
            "face_detected": True,
            "eyes_closed": False,
            "head_turned": False,
            "phone_detected": False,
            "dt": 0.05
        })

    assert tracker.pomodoro.remaining_seconds == frozen_time
    assert tracker.pomodoro.state == PomodoroState.FROZEN


def test_9_completing_punishment_resumes_original_pomodoro_correctly():
    tracker = SessionTracker()
    tracker.start_session(goal_minutes=25)
    tracker.pomodoro.freeze()
    frozen_rem = tracker.pomodoro.remaining_seconds

    # Fast 0.1s punishment for test
    tracker.punishment_mgr.duration_seconds = 0.1
    tracker.punishment_mgr.activate(frozen_rem, "10:00:00")
    tracker.status = SessionStatus.PUNISHMENT

    # Wait and tick until completed
    time.sleep(0.15)
    tracker.update({
        "face_detected": True,
        "eyes_closed": False,
        "head_turned": False,
        "phone_detected": False,
        "dt": 0.05
    })

    assert tracker.punishment_mgr.is_active is False
    assert tracker.status == SessionStatus.RUNNING
    assert tracker.pomodoro.state == PomodoroState.RUNNING
    # Pomodoro resumed from frozen value
    assert tracker.pomodoro.remaining_seconds <= frozen_rem


def test_10_continuous_event_cannot_repeatedly_trigger_flags():
    tracker = SessionTracker()
    tracker.settings.phone_duration_threshold = 0.5
    tracker.start_session(goal_minutes=25)

    # 10 consecutive frames of phone distraction should belong to the same single active event
    phone_frame = {
        "face_detected": True,
        "eyes_closed": False,
        "head_turned": False,
        "phone_detected": True,
        "phone_max_confidence": 0.9,
        "dt": 0.1
    }
    for _ in range(10):
        tracker.update(phone_frame)

    assert tracker.event_counter == 1
    assert tracker.current_active_event is not None
    # Flags are raised once the event ends
    assert tracker.flag_mgr.total_flags == 0

    # End the distraction by returning to focus
    focused_frame = {
        "face_detected": True,
        "eyes_closed": False,
        "head_turned": False,
        "phone_detected": False,
        "dt": 0.1
    }
    tracker.update(focused_frame)

    assert tracker.current_active_event is None
    assert tracker.flag_mgr.total_flags == 1

    # Another focused frame does not generate new flags
    tracker.update(focused_frame)
    assert tracker.flag_mgr.total_flags == 1


def test_11_simultaneous_detections_do_not_cause_unintended_duplicate_penalties():
    pen_mgr = PenaltyManager()
    initial_score = pen_mgr.score
    assert initial_score == 100

    # Apply penalty for event 1
    res1 = pen_mgr.apply_penalty(event_id=1, category="phone", reason="Phone", wall_time_str="10:00:00")
    assert res1["deducted"] == 10
    assert pen_mgr.score == 90

    # Duplicate call with event 1
    res2 = pen_mgr.apply_penalty(event_id=1, category="phone", reason="Phone", wall_time_str="10:00:00")
    assert res2["deducted"] == 0
    assert res2["already_counted"] is True
    assert pen_mgr.score == 90


def test_12_webcam_disconnection_pauses_punishment_timer_and_no_false_distractions():
    punish = PunishmentManager(duration_seconds=300, max_flags_allowed=1)
    punish.activate(frozen_pomodoro_remaining=1000.0, wall_time_str="10:00:00")

    # When monitoring_ok=False (camera disconnected / no face frame), timer must NOT advance
    rem_before = punish.remaining_seconds
    time.sleep(0.1)
    punish.tick(monitoring_ok=False)
    assert punish.remaining_seconds == rem_before


def test_13_browser_refresh_or_reconnection_does_not_create_duplicate_punishments():
    flag_mgr = FlagManager(max_flags=5)
    for i in range(1, 6):
        flag_mgr.try_raise_flag(event_id=i, category="phone", reason="Phone", wall_time_str=f"10:0{i}:00")

    assert flag_mgr.total_punishments_triggered == 1

    # Simulate reconnect: querying summary multiple times
    s1 = flag_mgr.get_summary()
    s2 = flag_mgr.get_summary()
    assert s1["total_punishments"] == 1
    assert s2["total_punishments"] == 1


def test_14_notifications_display_correct_messages_and_severity():
    flag_mgr = FlagManager(max_flags=5)
    # Flag 1
    f1 = flag_mgr.try_raise_flag(event_id=1, category="drowsy", reason="Eyes closed", wall_time_str="10:00:00")
    assert f1["severity"] == "info"
    assert "distracted" in f1["escalation_message"].lower()

    # Flag 2
    f2 = flag_mgr.try_raise_flag(event_id=2, category="gaze", reason="Gaze turned", wall_time_str="10:01:00")
    assert f2["severity"] == "warning"
    assert "second" in f2["escalation_message"].lower()

    # Flag 4
    flag_mgr.try_raise_flag(event_id=3, category="phone", reason="Phone", wall_time_str="10:02:00")
    f4 = flag_mgr.try_raise_flag(event_id=4, category="phone", reason="Phone", wall_time_str="10:03:00")
    assert f4["severity"] == "critical"
    assert "one more" in f4["escalation_message"].lower()

    # Flag 5
    f5 = flag_mgr.try_raise_flag(event_id=5, category="absence", reason="Absent", wall_time_str="10:04:00")
    assert f5["severity"] == "punishment"
    assert "discipline mode" in f5["escalation_message"].lower()


def test_15_final_report_contains_accurate_records():
    tracker = SessionTracker()
    tracker.settings.phone_duration_threshold = 0.1
    tracker.start_session(goal_minutes=25)

    # Simulate one completed distraction event (duration >= 0.5s)
    tracker.update({"face_detected": True, "eyes_closed": False, "head_turned": False, "phone_detected": True, "dt": 0.2})
    tracker.update({"face_detected": True, "eyes_closed": False, "head_turned": False, "phone_detected": True, "dt": 0.5})
    tracker.update({"face_detected": True, "eyes_closed": False, "head_turned": False, "phone_detected": False, "dt": 0.1})

    tracker.stop_session()
    report = ReportGenerator.generate_report(tracker)

    assert "discipline_summary" in report
    assert "flags_summary" in report
    assert "punishment_summary" in report
    assert "pomodoro_summary" in report
    assert "chronological_timeline" in report["events_summary"]
    assert report["discipline_summary"]["initial_score"] == 100
    assert report["flags_summary"]["total_flags"] == 1
    assert len(report["events_summary"]["chronological_timeline"]) >= 1
