from flask import Blueprint, request, jsonify, session
import datetime
from database import db, _session_lock, active_sessions, _state_lock, save_db, rewrite_attendance_csv_for_key, get_student_photo_b64
from auth import me
from config import TIME_SLOTS
import threading
from session_engine import get_faculty_sessions, generate_sessions_for_week, session_runner, current_slot_id, current_day

faculty_bp = Blueprint('faculty', __name__)


@faculty_bp.route("/faculty/calendar")
def faculty_calendar():
    u = me()
    if not u:
        return jsonify({"sessions": []}), 401
    week_offset = int(request.args.get("week", 0))
    uname = session.get("username")
    dept = u.get("department") or ""
    if not dept:
        for s in db["sessions"]:
            if s.get("faculty_username") == uname and s.get("dept"):
                dept = s["dept"]
                break
    # Generate sessions for the requested week
    generate_sessions_for_week(uname, dept, week_offset)
    sessions = get_faculty_sessions(uname, week_offset)
    for s in sessions:
        key = s.get("att_key", "")
        recs = db["attendance_records"].get(key, [])
        all_stu = db["students"].get(s["section"], [])
        total = len(all_stu)
        present = sum(1 for r in recs if r["status"] == "Present")
        s["att_count"] = present
        s["total_students"] = total
        # att_marked: true only when every student has a record
        s["att_marked"] = len(recs) >= total > 0
        orig_user = db["users"].get(s.get("faculty_username", ""), {})
        s["faculty_name"] = orig_user.get("name", s.get("faculty_username", ""))
        if s.get("substitute"):
            sub_user = db["users"].get(s["substitute"], {})
            s["substitute_name"] = sub_user.get("name", s["substitute"])
        else:
            s["substitute_name"] = None
    return jsonify({"sessions": sessions, "time_slots": TIME_SLOTS})

@faculty_bp.route("/faculty/session_detail")
def faculty_session_detail():
    u = me()
    if not u:
        return jsonify({}), 401
    session_id = request.args.get("id","")
    sess = next((s for s in db["sessions"] if s["id"] == session_id), None)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    uname = session.get("username")
    if sess["faculty_username"] != uname and sess.get("substitute") != uname:
        if u.get("role") not in ("admin","dept_head"):
            return jsonify({"error": "Forbidden"}), 403
    key = sess.get("att_key","")
    recs = db["attendance_records"].get(key, [])
    all_students = db["students"].get(sess["section"], [])
    present_rolls = {r["roll"] for r in recs if r["status"] == "Present"}
    student_list = []
    for stu in all_students:
        student_list.append({
            "roll": stu["roll"],
            "name": stu["name"],
            "status": "Present" if stu["roll"] in present_rolls else "Absent",
            "photo": get_student_photo_b64(stu["roll"]),
        })
    return jsonify({
        "session": sess,
        "students": student_list,
        "present_count": len(present_rolls),
        "total": len(all_students),
    })

@faculty_bp.route("/faculty/start_session", methods=["POST"])
def faculty_start_session():
    u = me()
    if not u:
        return jsonify({"success": False, "message": "Not logged in"}), 401
    d          = request.get_json(silent=True) or {}
    session_id = d.get("session_id", "")
    cam_id     = d.get("cam_id", "default")

    sess = next((s for s in db["sessions"] if s["id"] == session_id), None)
    if not sess:
        return jsonify({"success": False, "message": "Session not found"}), 404

    uname = session.get("username")
    if sess["faculty_username"] != uname and sess.get("substitute") != uname:
        if u.get("role") not in ("admin", "dept_head"):
            return jsonify({"success": False, "message": "Forbidden"}), 403

    # already running?
    with _session_lock:
        if session_id in active_sessions and active_sessions[session_id]["status"] in ("running", "finalizing"):
            info = active_sessions[session_id]
            return jsonify({
                "success": True,
                "already_running": True,
                "captures": info["captures"],
                "status": info["status"],
                "end_time": info["end_time"].strftime("%H:%M"),
                "finalize_at": (info["end_time"] - datetime.timedelta(minutes=1)).strftime("%H:%M"),
            })

    # parse slot end time to build end datetime
    slot_end_str = sess.get("slot_end", "")
    sess_date    = sess.get("date", datetime.date.today().isoformat())
    
    if sess_date != datetime.date.today().isoformat():
        return jsonify({"success": False, "message": "Attendance can only be captured on the exact day of the session"}), 403
    try:
        h, m = map(int, slot_end_str.split(":"))
        date_obj  = datetime.date.fromisoformat(sess_date)
        end_dt    = datetime.datetime.combine(date_obj, datetime.time(h, m))
    except Exception:
        return jsonify({"success": False, "message": "Could not parse slot end time"}), 400

    # If the class period is already over, still allow manual attendance marking
    # but don't start the auto-capture thread
    now = datetime.datetime.now()
    if now >= end_dt:
        # Allow session to be "started" for manual attendance even if time passed
        # Mark it completed immediately so manual save is still possible
        return jsonify({
            "success": False,
            "message": "Class period has ended. Use manual attendance marking below.",
            "period_ended": True,
        }), 200

    stop_evt = threading.Event()
    info = {
        "session_id": session_id,
        "section":    sess["section"],
        "slot_id":    sess["slot_id"],
        "dept":       sess.get("dept", u.get("department", "")),
        "faculty":    u.get("name", ""),
        "cam_id":     cam_id,
        "date":       sess_date,
        "end_time":   end_dt,
        "stop_event": stop_evt,
        "captures":   0,
        "detected_counts": {},
        "status":     "running",
        "started_at": now.isoformat(),
    }
    with _session_lock:
        active_sessions[session_id] = info

    t = threading.Thread(target=session_runner, args=(session_id,), daemon=True)
    info["thread"] = t
    t.start()

    return jsonify({
        "success": True,
        "message": "Session started — attendance will be captured automatically",
        "end_time": end_dt.strftime("%H:%M"),
        "finalize_at": (end_dt - datetime.timedelta(minutes=1)).strftime("%H:%M"),
    })

@faculty_bp.route("/faculty/session_status")
def faculty_session_status():
    u = me()
    if not u:
        return jsonify({}), 401
    session_id = request.args.get("id", "")
    with _session_lock:
        info = active_sessions.get(session_id)
    if not info:
        return jsonify({"active": False})

    section  = info["section"]
    slot_id  = info["slot_id"]
    date_str = info["date"]
    key      = f"{section}::{slot_id}::{date_str}"
    recs     = db["attendance_records"].get(key, [])
    total    = len(db["students"].get(section, []))
    present  = sum(1 for r in recs if r["status"] == "Present")

    # compute minutes remaining
    now = datetime.datetime.now()
    end_time = info["end_time"]
    mins_left = max(0, int((end_time - now).total_seconds() // 60))

    return jsonify({
        "active":    info["status"] in ("running", "finalizing"),
        "status":    info["status"],
        "captures":  info["captures"],
        "mins_left": mins_left,
        "end_time":  end_time.strftime("%H:%M"),
        "present":   present,
        "total":     total,
        "detected_preview": [
            {"name": name, "count": cnt}
            for name, cnt in sorted(info["detected_counts"].items(), key=lambda x: -x[1])
        ],
        "detected_counts": info["detected_counts"],
    })

@faculty_bp.route("/faculty/stop_session", methods=["POST"])
def faculty_stop_session():
    u = me()
    if not u:
        return jsonify({"success": False}), 401
    session_id = request.json.get("session_id")
    with _session_lock:
        info = active_sessions.get(session_id)
        if info and info["status"] in ("running", "finalizing"):
            info["stop_event"].set()
            return jsonify({"success": True})
    return jsonify({"success": False, "message": "Not running"})

@faculty_bp.route("/faculty/save_attendance", methods=["POST"])
def faculty_save_attendance():
    u = me()
    if not u:
        return jsonify({"success": False}), 401
    d        = request.get_json(silent=True) or {}
    section  = d.get("section", "")
    slot_id  = d.get("slot_id", "")
    date_str = d.get("date", datetime.date.today().isoformat())
    records  = d.get("records", [])
    dept     = u.get("department", "") or ""

    if not section or not slot_id:
        return jsonify({"success": False, "error": "section and slot_id required"}), 400

    if date_str != datetime.date.today().isoformat():
        return jsonify({"success": False, "error": "Attendance can only be marked on the exact day of the session"}), 403

    # Normalise records: ensure each has roll, name, status
    clean_records = []
    for r in records:
        if not r.get("roll"):
            continue
        clean_records.append({
            "roll":      r["roll"],
            "name":      r.get("name", r["roll"]),
            "status":    r.get("status", "Absent"),
            "time":      datetime.datetime.now().strftime("%H:%M:%S"),
            "marked_by": session.get("username", "faculty"),
        })

    key = f"{section}::{slot_id}::{date_str}"
    with _state_lock:
        db["attendance_records"][key] = clean_records
    save_db()
    # Use rewrite to avoid duplicate CSV rows on re-saves
    rewrite_attendance_csv_for_key(section, dept, slot_id, date_str, clean_records, u.get("name",""))
    return jsonify({"success": True, "saved": len(clean_records)})

@faculty_bp.route("/faculty/attendance_list")
def faculty_attendance_list():
    if not me():
        return jsonify({"records": []}), 401
    section  = request.args.get("section","")
    slot_id  = request.args.get("slot","")
    date_str = request.args.get("date", datetime.date.today().isoformat())
    key = f"{section}::{slot_id}::{date_str}"
    recs = db["attendance_records"].get(key, [])
    for r in recs:
        if "photo" not in r:
            r["photo"] = get_student_photo_b64(r["roll"])
    return jsonify({"records": recs, "count": len(recs)})

@faculty_bp.route("/faculty/slot_info")
def faculty_slot_info():
    if not me():
        return jsonify({}), 401
    sid = current_slot_id()
    day = current_day()
    return jsonify({
        "slot_id":    sid,
        "day":        day,
        "slot_label": next((s["label"] for s in TIME_SLOTS if s["id"]==sid), "—"),
        "slot_time":  next((f"{s['start']}–{s['end']}" for s in TIME_SLOTS if s["id"]==sid), ""),
        "time_slots": TIME_SLOTS,
    })

