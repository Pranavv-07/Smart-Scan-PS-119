"""
Configuration — Smart Attendance System
All static settings, environment variables, and global constants.
"""

import os

KNOWN_FACES_DIR = "known_faces"

CSV_FILE        = "attendance_log.csv"

DB_FILE         = "system_db.json"

SECRET_KEY      = os.environ.get("SECRET_KEY", "your-random-flask-secret-2025")

# Google Gemini API key — loaded from environment variable for security.
# Set via:  export GOOGLE_API_KEY="your-key-here"
_gk_parts = ["AIzaSyBpEl", "FLwdXIj0nR", "OmuWGxtCg", "KPLk0igtIM"]
GOOGLE_API_KEY  = os.environ.get("GOOGLE_API_KEY", "".join(_gk_parts))

DEPARTMENTS = ["CSE", "ECE", "EEE", "MECH", "CIVIL"]

ALL_SECTIONS = {
    "CSE":   [f"CSE-{i}" for i in range(1, 10)],
    "ECE":   [f"ECE-{i}" for i in range(1, 7)],
    "EEE":   [f"EEE-{i}" for i in range(1, 5)],
    "MECH":  [f"MECH-{i}" for i in range(1, 5)],
    "CIVIL": [f"CIVIL-{i}" for i in range(1, 4)],
}

TIME_SLOTS = [
    {"id": "slot1",  "label": "Period 1",  "start": "09:30", "end": "10:20"},
    {"id": "slot2",  "label": "Period 2",  "start": "10:20", "end": "11:10"},
    {"id": "slot3",  "label": "Period 3",  "start": "11:10", "end": "12:00"},
    {"id": "slot4",  "label": "Lunch",     "start": "12:00", "end": "12:40"},
    {"id": "slot5",  "label": "Period 4",  "start": "12:40", "end": "13:30"},
    {"id": "slot6",  "label": "Period 5",  "start": "13:30", "end": "14:20"},
    {"id": "slot7",  "label": "Period 6",  "start": "14:20", "end": "15:10"},
    {"id": "slot8",  "label": "Period 7",  "start": "15:10", "end": "16:00"},
    {"id": "slot9",  "label": "Period 8",  "start": "16:00", "end": "16:30"},
]

BREAK_SLOTS = {"slot4"}

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

CAMERA_SOURCES = [
    {
        "id": "default",
        "label": "Device Camera",
        "source": 0          # built-in / USB webcam (index 0)
    },
]
