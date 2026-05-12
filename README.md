# AI-Powered Smart Attendance System

A full-stack automated facial recognition platform that replaces manual attendance tracking with seamless real-time management. It combines computer vision (InsightFace + OpenCV), live UI synchronization, modular role-based dashboards, and automated session scheduling into a unified ecosystem for universities.

---

## Problem Statement

Educational institutions face several critical challenges in attendance management:

| Problem | Solution | Key Implementation |
|---------|----------|-------------------|
| Time Consumption | Automated facial recognition captures attendance in the background | `face_service.py`, `insightface`, `cv2` |
| Proxy Attendance | Liveness detection and multi-capture thresholds (≥2 captures) prevent spoofing | `session_engine.py`, `capture_frame_detections` |
| Exam Cheating | AI object detection scans for phones/chits and flags suspicious behavior | `proctor_engine.py`, Object Detection |
| Lack of Evidence | Automated screenshot captures and email alerts upon anomaly detection | `alert_service.py`, `smtplib` |
| Fragmented Timetables | Excel-based bulk upload and dynamic schedule mappings | `dept.py`, `openpyxl`, Timetable Grid |
| Lack of Insights | Bi-directional live sync with 8s polling to update UI dynamically | Frontend polling, `autoSessStats` UI |
| Rigid Systems | Manual "Stop Session" override and grace period attendance editing | `faculty.py`, `_state_lock` synchronization |

---

## System Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │  Vanilla JS  │  │  CSS Variables│ │  Real-time Polling  │ │
│  │  DOM Config  │  │  Responsive UI│ │  Camera Feeds       │ │
│  └──────┬───────┘  └──────┬───────┘  └─────────┬───────────┘ │
└─────────┼─────────────────┼────────────────────┼─────────────┘
          │ REST API        │ Video Stream       │ Interval
          ▼                 ▼                    ▼
┌──────────────────────────────────────────────────────────────┐
│                       Server Layer                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                   Flask + Python 3.9                    │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │  │
│  │  │Blueprints│ │ Services │ │Lock/Sync │ │ Routes   │  │  │
│  │  │   (5)    │ │   (4)    │ │ Threads  │ │  (40+)   │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Face Service │  │Session Engine│  │ Database Layer   │   │
│  │ InsightFace  │  │ Background   │  │ JSON + CSV Logs  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Vanilla JS, HTML, CSS | Lightweight, reactive dashboards |
| **Styling** | Native CSS Variables | Theming, dynamic styling, responsive design |
| **Backend** | Flask (Python 3.9) | Modular REST API and web server |
| **Computer Vision** | InsightFace, OpenCV | Facial recognition, embedding extraction, video feeds |
| **State/Data** | JSON Document + CSV | `system_db.json` (Truth), `attendance_log.csv` (Audit) |
| **Concurrency** | Python `threading` | Non-blocking camera loops and background session runners |
| **AI Assistant** | Google Gemini | Generative AI integrations |

---

## Project Structure

```text
PS119/
├── app.py                  # Minimal entry point, blueprint registration
├── config.py               # Static settings, global variables (TIME_SLOTS)
├── database.py             # Thread locks, JSON loads/saves, CSV engine
├── auth.py                 # Login, logout, session management
├── face_service.py         # OpenCV loop, InsightFace logic, embeddings
├── session_engine.py       # Threaded auto-capture runner, timetable mapping
├── faculty.py              # Faculty dashboard and schedule endpoints
├── dept.py                 # Department Head management endpoints
├── admin.py                # System admin user management
├── index.html              # Single-page frontend (all portals)
├── known_faces/            # Student face photos (roll_number.png)
├── evidence/               # Proctor screenshot captures
├── requirements.txt        # Python dependencies
└── .gitignore
```

---

## Features

### 1. Automated Facial Recognition
- Leverages `insightface` (buffalo_l model) for robust multi-face tracking and extraction.
- Detects multiple students simultaneously via RTSP or USB cameras.
- **Threshold Validation**: A student is only marked present after being detected securely in multiple frames (≥2 captures).
- Cosine-distance matching against pre-enrolled face embeddings in `known_faces/`.

### 2. Enterprise Anti-Cheating & AI Proctoring Pipeline
The system integrates an advanced, multi-stage AI proctoring engine that maintains academic integrity seamlessly alongside attendance. It processes a real-time temporal pipeline to evaluate suspicion logically, not just based on isolated frames.

- **Multi-Object Tracking & Identity Mapping**:
  - Uses **YOLOv8-face** (or RetinaFace) for multi-face detection in dense classroom scenes.
  - Leverages **ByteTrack** for persistent multi-object tracking, handling occlusion and minimizing ID switching.
  - Maps temporary technical tracker IDs to permanent **Roll Numbers** using **FaceNet & FAISS** similarity search.
- **Behavioral & Action Intelligence**:
  - **Head Pose & Gaze**: Uses **MediaPipe FaceMesh** to compute yaw/pitch/roll, identifying looking away, side gaze, or excessive head movement.
  - **Talking & Interaction**: Detects continuous lip motion and abnormal student proximity (leaning, face clustering).
  - **Missing Student**: Triggers when a mapped student disappears from the tracked scene beyond a timeout threshold.
- **Unauthorized Object Detection (YOLO)**:
  - Actively scans for **Phones/Mobile Devices** and **Chits/Paper notes**.
  - Identifies hand-to-face concealment or unusual reaching patterns under desks.
- **Temporal Suspicion Score Engine**:
  - Cheating is *never* triggered from a single frame. The engine uses a configurable rule-based scoring system (e.g., Phone = +50, Talking = +15).
  - Employs rolling windows, confidence accumulation, and automated score decay over time when behavior normalizes.
  - Generates Warning vs. Critical alerts based on severity escalation.
- **Evidence & Email Alert System**:
  - Automatically captures **screenshot evidence** (cropping the relevant student region).
  - Dispatches automated **email notifications** to supervisors containing the student's name, roll number, event type, confidence score, and timestamp.
- **Live Monitoring Dashboard**:
  - A unified WebSocket-streamed UI displaying bounding boxes, tracking IDs, live suspicion scores, and evidence thumbnails.
  - Color-coded monitoring (Green = Normal, Yellow = Suspicion, Red = Critical Alert) with an event timeline.

### 3. Role-Based Dashboards
- **Faculty Portal**: Live automated session tracking, calendar views, manual attendance overrides.
- **Department Portal**: Faculty management, bulk Excel timetable uploads, section-wise statistics.
- **Admin Portal**: System-wide access control and user provisioning.

### 4. Real-Time Collaboration & Sync
- Faculty UI dynamically polls the backend every 8 seconds during an active session.
- Student statuses toggle from "Absent" to "Present" in real-time as the camera recognizes them.
- Displays live statistics: "Captures", "Present Count", "Minutes Left".

### 5. Robust Scheduling Engine
- Automated generation of daily sessions mapped from departmental timetables.
- Supports substitute faculty assignments dynamically.
- Week navigation with session generation for ±4 weeks.

### 6. Seamless Excel Integration
- One-click bulk student enrollment via `.xlsx` templates.
- Full timetable uploads for the entire department in one operation.
- Downloadable cross-filtered Excel attendance reports.

---

## Quick Start

### Prerequisites
- Python 3.9+
- pip (Python package manager)
- Webcam (built-in or USB) for face recognition

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd PS119

# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Set environment variables (optional — defaults are provided):

```bash
export SECRET_KEY="your-random-flask-secret"
export GOOGLE_API_KEY="your-gemini-api-key"
```

### Running the Application

```bash
python3 app.py
```

The server starts at **http://localhost:8080**.

### Default Admin Login
- **Username**: `admin`
- **Password**: `admin123`

---

## User Journey

```text
Register/Login → Dashboard → Choose Role:
│
├─ Faculty Path:
│  └─ View Calendar → Start Live Session → Camera detects faces
│     → Real-time UI updates → Stop Session → Review & Save
│
├─ Dept Head Path:
│  └─ Manage Faculty → Upload Timetable Excel → Upload Students
│     → Monitor Analytics → Override Attendance (within 24h)
│
└─ Admin Path:
   └─ Provision Roles → Export System Logs → Global Overview
```

### Data Flow

```text
User Action → API Request → Blueprint Controller → Global State Lock
→ Session Engine / Face Service → `system_db.json` Write
→ CSV Audit Append → Response → UI State Update
```

---

## Enrolling Student Faces

Place student face photos in the `known_faces/` directory:
- **Filename format**: `<ROLL_NUMBER>.png` (e.g., `24B11CS355.png`)
- One clear, front-facing photo per student
- Supported formats: `.png`, `.jpg`, `.jpeg`

The system loads embeddings at startup and uses them for real-time matching.

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session signing secret | `your-random-flask-secret-2025` |
| `GOOGLE_API_KEY` | Gemini API key for AI integrations | Built-in (split for security) |

---

## API Endpoints Overview

| Endpoint | Method | Role | Description |
|----------|--------|------|-------------|
| `/login` | POST | All | Authenticate user |
| `/logout` | POST | All | Clear session |
| `/check_session` | GET | All | Verify login state |
| `/faculty/calendar` | GET | Faculty | Weekly calendar with sessions |
| `/faculty/start_session` | POST | Faculty | Start auto-attendance capture |
| `/faculty/stop_session` | POST | Faculty | Manually stop running session |
| `/faculty/save_attendance` | POST | Faculty | Save manual attendance |
| `/dept/faculty_list` | GET | Dept Head | List department faculty |
| `/dept/save_timetable` | POST | Dept Head | Save timetable entries |
| `/dept/upload_timetable_excel` | POST | Dept Head | Bulk timetable import |
| `/dept/sessions` | GET | Dept Head | View department sessions |
| `/dept/analytics` | GET | Dept Head | Section attendance analytics |
| `/admin/all_users` | GET | Admin | List all system users |
| `/admin/export_csv` | GET | Admin | Download attendance CSV |

---

## Future Scope

1. **Database Migration**: Move from JSON/CSV file storage to PostgreSQL for massive scalability.
2. **Multi-Camera Mesh**: Support multiple synchronized camera streams parsing identical sessions in large halls.
3. **Advanced Liveness**: Implement blink/depth detection to prevent photo spoofing.
4. **Mobile Application**: Faculty companion app for taking manual attendance via mobile.

---

## License

This project is developed as an academic/educational platform.
