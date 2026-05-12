import json, os, csv, datetime, hashlib, threading, base64
from config import *


_state_lock = threading.Lock()

_session_lock = threading.Lock()

active_sessions = {}

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _default_db():
    return {
        "users": {
            "admin": {
                "password_hash": _hash("admin123"),
                "role": "admin",
                "department": None,
                "name": "System Administrator",
                "sections": []
            }
        },
        "timetable": {},
        "students":  {s: [] for dept in ALL_SECTIONS for s in ALL_SECTIONS[dept]},
        "camera_map": {s: "default" for dept in ALL_SECTIONS for s in ALL_SECTIONS[dept]},
        "sessions": [],
        "attendance_records": {},
    }

def load_db() -> dict:
    default = _default_db()
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f:
                saved = json.load(f)
            for k, v in default.items():
                if k not in saved:
                    saved[k] = v
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        saved[k].setdefault(k2, v2)
            return saved
        except Exception as e:
            print(f"⚠️  DB load error: {e} — using default")
    return default

db = load_db()

def save_db():
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def setup_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(
                ["Roll", "Name", "Section", "Department", "Slot", "Subject",
                 "Faculty", "Date", "Time", "Status"])

def write_attendance_csv(roll, name, section, dept, slot_id, subject, faculty, status="Present"):
    """Append one row to the CSV log. Duplicates are possible if the same session
    is saved multiple times; use the JSON attendance_records as the authoritative
    source of truth and treat the CSV as an audit trail only."""
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow(
            [roll, name, section, dept, slot_id, subject, faculty, date_str, time_str, status])

def rewrite_attendance_csv_for_key(section, dept, slot_id, date_str, records, faculty):
    """Rewrite ALL rows for a specific section+slot+date in the CSV to avoid duplicates.
    Called by faculty_save_attendance and dept_update_attendance on every manual save."""
    CANONICAL_FIELDS = ["Roll","Name","Section","Department","Slot","Subject","Faculty","Date","Time","Status"]
    if not os.path.exists(CSV_FILE):
        setup_csv()
    # Read existing rows that are NOT for this key
    kept_rows = []
    try:
        with open(CSV_FILE, newline="") as f:
            reader = csv.DictReader(f)
            old_fields = reader.fieldnames or []
            # Only keep old rows if the CSV has the canonical headers
            if set(CANONICAL_FIELDS).issubset(set(old_fields)):
                for row in reader:
                    if not (row.get("Section") == section and row.get("Slot") == slot_id and row.get("Date") == date_str):
                        kept_rows.append({k: row.get(k,"") for k in CANONICAL_FIELDS})
    except Exception:
        pass
    # Rewrite file with canonical headers + kept rows + fresh records for this key
    time_str = datetime.datetime.now().strftime("%H:%M:%S")
    with open(CSV_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL_FIELDS)
        w.writeheader()
        w.writerows(kept_rows)
        for r in records:
            w.writerow({
                "Roll": r["roll"], "Name": r.get("name",""), "Section": section,
                "Department": dept, "Slot": slot_id, "Subject": "",
                "Faculty": faculty, "Date": date_str, "Time": time_str,
                "Status": r.get("status","Absent"),
            })


def get_student_photo_b64(roll: str):
    """Return a data-URI base64 string for the student's face photo, or None."""
    for ext in (".jpg", ".jpeg", ".png"):
        path = os.path.join(KNOWN_FACES_DIR, roll + ext)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
                return f"data:{mime};base64,{data}"
            except Exception:
                pass
    return None
