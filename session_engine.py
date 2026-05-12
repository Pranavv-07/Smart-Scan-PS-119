import datetime, threading
from database import _session_lock, active_sessions, _state_lock, db, save_db, rewrite_attendance_csv_for_key
from config import TIME_SLOTS, DAYS, BREAK_SLOTS
from face_service import capture_frame_detections


def current_slot_id():
    now = datetime.datetime.now().strftime("%H:%M")
    for slot in TIME_SLOTS:
        if slot["start"] <= now < slot["end"]:
            return slot["id"]
    return None

def current_day() -> str:
    return datetime.datetime.now().strftime("%A")

def generate_sessions_for_week(faculty_username: str, dept: str, week_offset: int = 0):
    tt = db["timetable"].get(faculty_username, {})
    if not tt:
        return
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    day_offsets = {d: i for i, d in enumerate(DAYS)}

    # Build index of existing sessions by composite key for fast lookup
    existing_by_key = {}
    for s in db["sessions"]:
        k = f"{s['faculty_username']}::{s['date']}::{s['slot_id']}::{s['section']}"
        existing_by_key[k] = s

    new_sessions = []
    changed = False
    for day_name, slots in tt.items():
        offset = day_offsets.get(day_name)
        if offset is None:
            continue
        date_obj = monday + datetime.timedelta(days=offset)
        date_str = date_obj.isoformat()
        for slot_id, entry in slots.items():
            if slot_id in BREAK_SLOTS:
                continue
            section = entry.get("section", "")
            subject  = entry.get("subject", "")
            if not section:
                continue
            key = f"{faculty_username}::{date_str}::{slot_id}::{section}"
            slot_info = next((s for s in TIME_SLOTS if s["id"] == slot_id), {})
            if key in existing_by_key:
                # Update mutable fields so dept_head edits always reflect
                sess = existing_by_key[key]
                updated = False
                if sess.get("subject") != subject:
                    sess["subject"] = subject; updated = True
                if sess.get("dept") != dept:
                    sess["dept"] = dept; updated = True
                if sess.get("slot_start") != slot_info.get("start", ""):
                    sess["slot_start"] = slot_info.get("start", ""); updated = True
                if sess.get("slot_end") != slot_info.get("end", ""):
                    sess["slot_end"] = slot_info.get("end", ""); updated = True
                # Always keep att_key in sync with section+slot+date
                expected_att_key = f"{section}::{slot_id}::{date_str}"
                if sess.get("att_key") != expected_att_key:
                    sess["att_key"] = expected_att_key; updated = True
                if updated:
                    changed = True
            else:
                new_sessions.append({
                    "id": f"{faculty_username}_{date_str}_{slot_id}_{section}",
                    "date": date_str,
                    "section": section,
                    "slot_id": slot_id,
                    "slot_label": slot_info.get("label", slot_id),
                    "slot_start": slot_info.get("start", ""),
                    "slot_end": slot_info.get("end", ""),
                    "subject": subject,
                    "faculty_username": faculty_username,
                    "dept": dept,
                    "status": "scheduled",
                    "substitute": None,
                    "att_key": f"{section}::{slot_id}::{date_str}",
                })

    if new_sessions:
        db["sessions"].extend(new_sessions)
        changed = True
    if changed:
        save_db()

def get_faculty_sessions(faculty_username: str, week_offset: int = 0):
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    sunday = monday + datetime.timedelta(days=6)
    result = []
    for s in db["sessions"]:
        if s.get("faculty_username") != faculty_username and s.get("substitute") != faculty_username:
            continue
        try:
            d = datetime.date.fromisoformat(s["date"])
        except Exception:
            continue
        if monday <= d <= sunday:
            result.append(s)
    return result

def session_runner(session_id: str):
    """
    Background thread that auto-captures attendance at random ~10-min intervals.
    Finalizes 1 minute before class ends.
    A student is marked Present if detected in ≥2 captures.
    """
    with _session_lock:
        info = active_sessions.get(session_id)
    if not info:
        return

    stop_evt      = info["stop_event"]
    end_time      = info["end_time"]          # datetime
    section       = info["section"]
    slot_id       = info["slot_id"]
    dept          = info["dept"]
    faculty       = info["faculty"]
    cam_id        = info["cam_id"]
    date_str      = info["date"]
    stu_name_to_roll = {s["name"]: s["roll"] for s in db["students"].get(section, [])}

    finalize_at = end_time - datetime.timedelta(minutes=1)
    INTERVAL_BASE = 10 * 60   # 10 minutes in seconds
    INTERVAL_JITTER = 90      # ±90 seconds

    def do_capture():
        detected = capture_frame_detections(cam_id)
        with _session_lock:
            sess = active_sessions.get(session_id)
            if sess is None:
                return
            sess["captures"] += 1
            for name in detected:
                sess["detected_counts"][name] = sess["detected_counts"].get(name, 0) + 1

    def finalize():
        with _session_lock:
            sess = active_sessions.get(session_id)
            if sess is None:
                return
            sess["status"] = "finalizing"
            detected_counts = dict(sess["detected_counts"])

        # Mark present if detected in ≥2 captures
        present_names = {name for name, cnt in detected_counts.items() if cnt >= 2}
        all_students  = db["students"].get(section, [])
        key = f"{section}::{slot_id}::{date_str}"
        now_str = datetime.datetime.now().strftime("%H:%M:%S")

        with _state_lock:
            # Build a fresh authoritative list — upsert every student
            roll_to_rec = {}
            for r in db["attendance_records"].get(key, []):
                roll_to_rec[r["roll"]] = r

            for stu in all_students:
                roll   = stu["roll"]
                name   = stu["name"]
                status = "Present" if name in present_names else "Absent"
                roll_to_rec[roll] = {
                    "roll": roll, "name": name, "status": status,
                    "time": now_str, "marked_by": "auto_session"
                }

            db["attendance_records"][key] = list(roll_to_rec.values())
        # Rewrite CSV for this key to avoid duplicates from multiple finalize attempts
        rewrite_attendance_csv_for_key(section, dept, slot_id, date_str,
                                       db["attendance_records"][key], faculty)
        save_db()

        with _session_lock:
            sess = active_sessions.get(session_id)
            if sess:
                sess["status"] = "completed"

    # ── main loop ──────────────────────────────────────────────────────────────
    # Do an initial capture shortly after start (30–90 s)
    first_wait = 30 + (hash(session_id) % 60)
    stop_evt.wait(timeout=first_wait)
    if stop_evt.is_set():
        finalize(); return
    do_capture()

    import random
    while True:
        now = datetime.datetime.now()
        if now >= finalize_at:
            finalize()
            return

        # Sleep until next capture or finalize time
        next_capture = now + datetime.timedelta(
            seconds=INTERVAL_BASE + random.randint(-INTERVAL_JITTER, INTERVAL_JITTER))
        sleep_until  = min(next_capture, finalize_at)
        secs_to_sleep = (sleep_until - datetime.datetime.now()).total_seconds()
        if secs_to_sleep > 0:
            stop_evt.wait(timeout=secs_to_sleep)
        if stop_evt.is_set():
            finalize(); return
        now = datetime.datetime.now()
        if now >= finalize_at:
            finalize(); return
        do_capture()

