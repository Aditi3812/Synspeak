import json
from datetime import datetime
from typing import Dict, Any, List

from app.session_tracker import SessionTracker

def format_duration(seconds: float) -> str:
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:02d}m {secs:02d}s"

class ReportGenerator:
    """
    Generates comprehensive, ethically grounded Study Session Behavioral Reports
    with statistical breakdowns, yawn analysis, distraction flags, penalty points,
    punishment (One-Flag Challenge) tracking, and chronological timeline.
    """

    @staticmethod
    def generate_report(tracker: SessionTracker) -> Dict[str, Any]:
        start_dt = tracker.start_timestamp or datetime.now()
        end_dt = tracker.end_timestamp or datetime.now()
        
        total_s = max(0.1, tracker.total_elapsed_seconds)
        focused_s = tracker.focused_seconds
        distracted_s = tracker.total_distracted_seconds
        phone_s = tracker.phone_distracted_seconds
        gaze_s = tracker.gaze_distracted_seconds
        drowsy_s = tracker.drowsy_distracted_seconds
        yawn_s = tracker.yawn_distracted_seconds
        absent_s = tracker.absent_seconds
        unknown_s = tracker.unknown_seconds
        
        events: List[Dict[str, Any]] = list(tracker.distraction_events)
        total_events = len(events)
        
        avg_event_dur = round(sum(e["duration_s"] for e in events) / total_events, 1) if total_events > 0 else 0.0
        longest_event = max(events, key=lambda e: e["duration_s"]) if total_events > 0 else None

        # Breakdown counts by category
        phone_events = [e for e in events if e.get("category") == "phone"]
        gaze_events = [e for e in events if e.get("category") == "gaze"]
        drowsy_events = [e for e in events if e.get("category") == "drowsy"]
        yawn_events = [e for e in events if e.get("category") == "yawn"]
        absence_events = [e for e in events if e.get("category") == "absence"]

        # Flags by category
        flags_grouped = {}
        for f in tracker.flag_mgr.session_flags:
            cat = f.get("category", "other")
            flags_grouped[cat] = flags_grouped.get(cat, 0) + 1

        # Build chronological timeline
        timeline_entries = []
        for e in events:
            pen = e.get("penalty", 0)
            flag_str = f" — 1 flag" if e.get("flag_id") else ""
            pen_str = f" — {pen} points deducted" if pen > 0 else ""
            desc = f"{e.get('reason')} — {e.get('duration_s')}s{flag_str}{pen_str}"
            timeline_entries.append({
                "timestamp": e.get("start_time"),
                "type": "distraction",
                "category": e.get("category"),
                "description": desc,
                "duration_s": e.get("duration_s"),
                "penalty": pen,
                "flag_id": e.get("flag_id")
            })

        for p in tracker.punishment_mgr.punishment_history:
            timeline_entries.append({
                "timestamp": p.get("activation_time"),
                "type": "punishment_start",
                "description": "Fifth flag reached — One-Flag Challenge activated (5 min punishment study)",
                "duration_s": 0
            })
            if p.get("completion_time"):
                timeline_entries.append({
                    "timestamp": p.get("completion_time"),
                    "type": "punishment_end",
                    "description": f"One-Flag Challenge completed ({p.get('seconds_served', 300)}s served, {p.get('resets', 0)} resets) — Pomodoro resumed",
                    "duration_s": p.get("seconds_served", 0)
                })

        for r in tracker.penalty_mgr.reward_history:
            timeline_entries.append({
                "timestamp": r.get("timestamp"),
                "type": "focus_reward",
                "description": f"Focus streak achieved ({r.get('streak_seconds')}s) — +{r.get('reward_points')} points awarded",
                "duration_s": r.get("streak_seconds")
            })

        timeline_entries.sort(key=lambda x: str(x.get("timestamp", "")))

        # Behavioral Insights Generation
        insights = []
        if tracker.concentration_percentage >= 85:
            insights.append({
                "type": "positive",
                "title": "High Observable Engagement",
                "detail": "Observed behaviours showed consistent on-screen gaze and minimal phone or absence interruptions."
            })
        elif tracker.concentration_percentage >= 65:
            insights.append({
                "type": "neutral",
                "title": "Moderate Engagement Pattern",
                "detail": "Regular study activity observed with periodic shifts in gaze or brief interruptions."
            })
        else:
            insights.append({
                "type": "advisory",
                "title": "Frequent Behavioural Interruptions",
                "detail": "Substantial time was spent with the head turned away, phone visible, or absent from view."
            })

        if len(phone_events) > 0 or phone_s > 5:
            insights.append({
                "type": "phone",
                "title": "Mobile Phone Visibility Detected",
                "detail": f"A mobile phone was visible in the camera frame {len(phone_events)} time(s) for a total of {format_duration(phone_s)}. Storing phones out of reach during deep work blocks can reduce habitual checking."
            })

        if len(yawn_events) > 0 or yawn_s > 5:
            insights.append({
                "type": "yawn",
                "title": "Yawning Patterns Observed",
                "detail": f"Observed {len(yawn_events)} yawning episode(s) ({format_duration(yawn_s)}). Yawning is a natural physiological response to oxygen levels or mental fatigue. Consider ventilating the study room, drinking water, or taking a 5-minute stretch."
            })

        if len(drowsy_events) > 0 or drowsy_s > 15:
            insights.append({
                "type": "rest",
                "title": "Prolonged Eye Closures Noted",
                "detail": f"Observed {len(drowsy_events)} episodes of prolonged closed eyes ({format_duration(drowsy_s)}). This may correlate with visual fatigue or drowsiness."
            })

        if len(gaze_events) > 2 or gaze_s > 30:
            insights.append({
                "type": "gaze",
                "title": "Frequent Head Shifts",
                "detail": f"Head was turned away from screen {len(gaze_events)} time(s) for {format_duration(gaze_s)}. Note: If you were reading physical textbooks or handwritten notes, this is productive study behavior that our camera simply cannot classify."
            })

        if absent_s > 60:
            insights.append({
                "type": "absence",
                "title": "Desk Absence Intervals",
                "detail": f"Total time away from camera frame was {format_duration(absent_s)}. If these were planned breaks, that aligns with healthy study rhythms!"
            })

        if tracker.flag_mgr.total_flags >= 5 or tracker.flag_mgr.total_punishments_triggered > 0:
            insights.append({
                "type": "flags",
                "title": "One-Flag Challenge Punishments Triggered",
                "detail": f"The session accumulated {tracker.flag_mgr.total_flags} distraction flags and activated {tracker.flag_mgr.total_punishments_triggered} One-Flag Challenge punishment period(s)."
            })

        report = {
            "session_id": f"SESSION-{start_dt.strftime('%Y%m%d-%H%M%S')}",
            "generated_at": datetime.now().isoformat(),
            "timestamps": {
                "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_dt.strftime("%Y-%m-%d %H:%M:%S")
            },
            "durations": {
                "total_seconds": round(total_s, 1),
                "total_formatted": format_duration(total_s),
                "focused_seconds": round(focused_s, 1),
                "focused_formatted": format_duration(focused_s),
                "distracted_seconds": round(distracted_s, 1),
                "distracted_formatted": format_duration(distracted_s),
                "absent_seconds": round(absent_s, 1),
                "absent_formatted": format_duration(absent_s),
                "unknown_seconds": round(unknown_s, 1),
                "unknown_formatted": format_duration(unknown_s),
            },
            "percentages": {
                "concentration_score": tracker.concentration_percentage,
                "focused_ratio": round((focused_s / total_s) * 100, 1),
                "distracted_ratio": round((distracted_s / total_s) * 100, 1),
                "absent_ratio": round((absent_s / total_s) * 100, 1),
                "unknown_ratio": round((unknown_s / total_s) * 100, 1),
            },
            "discipline_summary": {
                "initial_score": 100,
                "final_score": tracker.penalty_mgr.score,
                "total_deductions": tracker.penalty_mgr.total_deducted,
                "total_rewards": tracker.penalty_mgr.total_rewarded,
                "longest_focus_streak_seconds": round(tracker.penalty_mgr.longest_streak_seconds, 1),
                "longest_focus_streak_formatted": format_duration(tracker.penalty_mgr.longest_streak_seconds),
                "total_qualified_focus_seconds": round(tracker.penalty_mgr.total_qualified_focus_seconds, 1),
                "penalties_history": tracker.penalty_mgr.penalty_history,
                "rewards_history": tracker.penalty_mgr.reward_history
            },
            "flags_summary": {
                "total_flags": tracker.flag_mgr.total_flags,
                "active_cycle_flags": tracker.flag_mgr.cycle_flags,
                "flags_by_category": flags_grouped,
                "all_flags": tracker.flag_mgr.session_flags
            },
            "punishment_summary": {
                "total_punishments_triggered": tracker.flag_mgr.total_punishments_triggered,
                "total_punishment_time_served_seconds": round(tracker.punishment_mgr.total_punishment_seconds_served, 1),
                "total_punishment_time_served_formatted": format_duration(tracker.punishment_mgr.total_punishment_seconds_served),
                "total_resets": tracker.punishment_mgr.reset_count,
                "punishment_history": tracker.punishment_mgr.punishment_history
            },
            "pomodoro_summary": {
                "goal_minutes": tracker.goal_minutes,
                "pomodoro_study_time_seconds": round(tracker.pomodoro.elapsed_seconds, 1),
                "pomodoro_study_time_formatted": format_duration(tracker.pomodoro.elapsed_seconds),
                "pomodoro_remaining_seconds": tracker.pomodoro.remaining_seconds,
                "is_completed": tracker.pomodoro.state.value == "COMPLETED"
            },
            "distraction_breakdown": {
                "phone": {
                    "seconds": round(phone_s, 1),
                    "formatted": format_duration(phone_s),
                    "events_count": len(phone_events),
                    "percentage_of_distraction": round((phone_s / max(0.1, distracted_s)) * 100, 1)
                },
                "gaze": {
                    "seconds": round(gaze_s, 1),
                    "formatted": format_duration(gaze_s),
                    "events_count": len(gaze_events),
                    "percentage_of_distraction": round((gaze_s / max(0.1, distracted_s)) * 100, 1)
                },
                "drowsy": {
                    "seconds": round(drowsy_s, 1),
                    "formatted": format_duration(drowsy_s),
                    "events_count": len(drowsy_events),
                    "percentage_of_distraction": round((drowsy_s / max(0.1, distracted_s)) * 100, 1)
                },
                "yawn": {
                    "seconds": round(yawn_s, 1),
                    "formatted": format_duration(yawn_s),
                    "events_count": len(yawn_events),
                    "percentage_of_distraction": round((yawn_s / max(0.1, distracted_s)) * 100, 1)
                },
                "absence": {
                    "seconds": round(absent_s, 1),
                    "formatted": format_duration(absent_s),
                    "events_count": len(absence_events)
                }
            },
            "events_summary": {
                "total_count": total_events,
                "average_duration_seconds": avg_event_dur,
                "average_duration_formatted": format_duration(avg_event_dur),
                "longest_event": longest_event,
                "all_events": events,
                "chronological_timeline": timeline_entries
            },
            "insights": insights,
            "timeline_samples": tracker.timeline_samples,
            "engineering_and_ethical_disclaimer": {
                "notice": "Observable Behavioural Estimation — Not Mental Focus Measurement",
                "principles": [
                    "Facial landmarks and camera images estimate observable behaviours, which can only correlate with attention, not mental concentration.",
                    "Looking away does not prove distraction (the student could be reading notes, solving problems on paper, or thinking deeply).",
                    "Closing eyes does not prove sleep or drowsiness (the student could be resting tired eyes or mentally synthesizing concepts).",
                    "Yawning indicates physical fatigue or oxygenation changes, not necessarily disinterest.",
                    "Absence from the camera frame proves absence from view, not cessation of academic study.",
                    "Mobile phone visibility proves presence of the device in camera frame, not active usage.",
                    "Looking directly towards the screen does not prove cognitive concentration."
                ]
            }
        }
        return report
