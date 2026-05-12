"""
Anti-Cheat Proctoring Engine
Real-time YOLO-based detection of phones, chits/paper, and suspicious behaviour.
Alerts with student roll number, evidence snapshot, and severity.
"""

from flask import Blueprint, Response, jsonify, request
import cv2, numpy as np, os, time, threading, datetime, base64
from database import db, get_student_photo_b64
from config import KNOWN_FACES_DIR
from face_service import frame_lock, camera_frames

try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

proctor_bp = Blueprint('proctor', __name__)

# ── State ────────────────────────────────────────────────────────────────────
yolo_model = None
proctor_lock = threading.Lock()
proctor_state = {
    "active": False,
    "cam_id": "default",
    "alerts": [],            # list of alert dicts
    "stop_event": None,
    "thread": None,
    "started_at": None,
    "latest_frame": None,    # annotated frame for video feed
    "stats": {"phones": 0, "chits": 0, "suspicious": 0, "total": 0},
}

# COCO classes that indicate malpractice
SUSPICIOUS_CLASSES = {
    67: {"label": "📱 Phone Detected", "short": "Phone", "severity": "critical",
         "color": (0, 0, 255), "score": 50},
    73: {"label": "📄 Chit / Paper", "short": "Chit", "severity": "warning",
         "color": (0, 165, 255), "score": 30},
    # 'book' in COCO — can also catch visible chit sheets
}

# Face model for matching (reuse from face_service if available)
proctor_face_app = None
proctor_known_embeddings = {}


def init_proctor():
    """Load YOLOv8 model and face model for proctor."""
    global yolo_model, proctor_face_app, proctor_known_embeddings
    # Load YOLO
    if YOLO_AVAILABLE:
        model_path = "yolov8n.pt"
        if os.path.exists(model_path):
            yolo_model = YOLO(model_path)
            print("✓ YOLOv8 loaded for anti-cheat proctoring")
        else:
            print("⚠️  yolov8n.pt not found — proctoring object detection disabled")
    else:
        print("⚠️  ultralytics not installed — proctoring object detection disabled")

    # Reuse existing face embeddings from face_service
    try:
        from face_service import face_app as fa, known_embeddings as ke
        proctor_face_app = fa
        proctor_known_embeddings = ke
    except Exception:
        pass


def _cosine_dist(e1, e2):
    return 1 - np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-9)


def _match_face(emb):
    """Match embedding to known students. Returns (roll, distance)."""
    best, dist = None, float("inf")
    for name, ref in proctor_known_embeddings.items():
        d = _cosine_dist(emb, ref)
        if d < dist:
            dist, best = d, name
    return best, dist


def _find_student_name(roll):
    """Look up student name from roll number across all sections."""
    for section_students in db["students"].values():
        for stu in section_students:
            if stu["roll"] == roll:
                return stu["name"]
    return None


def _proctor_loop(cam_id):
    """Background thread: runs YOLO on camera frames and generates alerts."""
    CONF_THRESHOLD = 0.15
    DEDUP_SECONDS = 5  # don't repeat same type+student within this window

    while not proctor_state["stop_event"].is_set():
        # Get the current frame
        with frame_lock:
            raw_frame = camera_frames.get(cam_id)
        if raw_frame is None:
            time.sleep(0.1)
            continue

        frame = raw_frame.copy()
        new_alerts = []

        # ── YOLO detection ───────────────────────────────────────────────
        if yolo_model is not None:
            results = yolo_model(frame, verbose=False, conf=CONF_THRESHOLD)
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    if cls_id not in SUSPICIOUS_CLASSES:
                        continue
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    obj_info = SUSPICIOUS_CLASSES[cls_id]

                    # Draw detection box on frame
                    cv2.rectangle(frame, (x1, y1), (x2, y2), obj_info["color"], 3)
                    label_text = f"{obj_info['short']} {conf:.0%}"
                    cv2.putText(frame, label_text, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, obj_info["color"], 2)

                    # ── Try to identify nearest student ──────────────────
                    student_roll = None
                    student_name = None
                    if proctor_face_app and INSIGHTFACE_AVAILABLE:
                        try:
                            faces = proctor_face_app.get(frame)
                            obj_cx = (x1 + x2) // 2
                            obj_cy = (y1 + y2) // 2
                            min_d = float("inf")
                            closest_face = None
                            for face in faces:
                                fx1, fy1, fx2, fy2 = face.bbox.astype(int)
                                fcx, fcy = (fx1 + fx2) // 2, (fy1 + fy2) // 2
                                d = np.sqrt((obj_cx - fcx) ** 2 + (obj_cy - fcy) ** 2)
                                if d < min_d:
                                    min_d = d
                                    closest_face = face
                            if closest_face is not None and min_d < 400:
                                roll, dist = _match_face(closest_face.embedding)
                                if roll and dist < 0.6:
                                    student_roll = roll
                                    student_name = _find_student_name(roll)
                                    # Draw face box + roll number
                                    bx = closest_face.bbox.astype(int)
                                    cv2.rectangle(frame, (bx[0], bx[1]), (bx[2], bx[3]),
                                                  (0, 255, 0), 2)
                                    cv2.putText(frame, student_roll,
                                                (bx[0], bx[1] - 8),
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                                (0, 255, 0), 2)
                        except Exception:
                            pass

                    # ── Crop evidence screenshot ─────────────────────────
                    pad = 30
                    ey1 = max(0, y1 - pad)
                    ey2 = min(frame.shape[0], y2 + pad)
                    ex1 = max(0, x1 - pad)
                    ex2 = min(frame.shape[1], x2 + pad)
                    evidence_crop = frame[ey1:ey2, ex1:ex2]
                    _, buf = cv2.imencode(".jpg", evidence_crop,
                                         [cv2.IMWRITE_JPEG_QUALITY, 85])
                    evidence_b64 = base64.b64encode(buf.tobytes()).decode()

                    new_alerts.append({
                        "type": obj_info["short"],
                        "label": obj_info["label"],
                        "severity": obj_info["severity"],
                        "score": obj_info["score"],
                        "student_roll": student_roll or "Unknown",
                        "student_name": student_name or "Unidentified",
                        "confidence": round(conf * 100, 1),
                        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                        "evidence": f"data:image/jpeg;base64,{evidence_b64}",
                        "photo": get_student_photo_b64(student_roll) if student_roll else None,
                    })

        # ── Also draw a timestamp overlay ────────────────────────────────
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, f"PROCTOR MODE | {ts}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

        # ── Store annotated frame ────────────────────────────────────────
        with proctor_lock:
            proctor_state["latest_frame"] = frame

        # ── Deduplicate and store alerts ──────────────────────────────────
        if new_alerts:
            now = datetime.datetime.now()
            with proctor_lock:
                for alert in new_alerts:
                    # Check for recent duplicate
                    dup = False
                    for existing in proctor_state["alerts"][-50:]:
                        if (existing["student_roll"] == alert["student_roll"]
                                and existing["type"] == alert["type"]):
                            try:
                                t = datetime.datetime.strptime(existing["timestamp"], "%H:%M:%S")
                                t = t.replace(year=now.year, month=now.month, day=now.day)
                                if (now - t).total_seconds() < DEDUP_SECONDS:
                                    dup = True
                                    break
                            except Exception:
                                pass
                    if not dup:
                        alert["id"] = f"alert_{len(proctor_state['alerts'])}_{time.time()}"
                        proctor_state["alerts"].append(alert)
                        # Update stats
                        proctor_state["stats"]["total"] += 1
                        if alert["type"] == "Phone":
                            proctor_state["stats"]["phones"] += 1
                        elif alert["type"] == "Chit":
                            proctor_state["stats"]["chits"] += 1
                        else:
                            proctor_state["stats"]["suspicious"] += 1

        time.sleep(0.5)  # ~2 FPS for detection to reduce CPU load


def _gen_proctor_frames():
    """Generator for annotated video stream."""
    while proctor_state["active"]:
        with proctor_lock:
            frame = proctor_state.get("latest_frame")
        if frame is None:
            # Fallback: show raw camera frame
            with frame_lock:
                frame = camera_frames.get(proctor_state["cam_id"])
            if frame is None:
                time.sleep(0.05)
                continue
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
               + buf.tobytes() + b"\r\n")
        time.sleep(0.06)


# ═══════════════════════════════════════════════════════════════════════════
#  API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@proctor_bp.route("/proctor/start", methods=["POST"])
def proctor_start():
    d = request.get_json(silent=True) or {}
    cam_id = d.get("cam_id", "default")

    with proctor_lock:
        if proctor_state["active"]:
            return jsonify({"success": True, "already_running": True})

        proctor_state["active"] = True
        proctor_state["cam_id"] = cam_id
        proctor_state["alerts"] = []
        proctor_state["stats"] = {"phones": 0, "chits": 0, "suspicious": 0, "total": 0}
        proctor_state["started_at"] = datetime.datetime.now().isoformat()
        proctor_state["latest_frame"] = None
        stop_evt = threading.Event()
        proctor_state["stop_event"] = stop_evt

    t = threading.Thread(target=_proctor_loop, args=(cam_id,), daemon=True)
    proctor_state["thread"] = t
    t.start()

    return jsonify({"success": True, "message": "Proctor mode started"})


@proctor_bp.route("/proctor/stop", methods=["POST"])
def proctor_stop():
    with proctor_lock:
        if proctor_state["stop_event"]:
            proctor_state["stop_event"].set()
        proctor_state["active"] = False

    return jsonify({"success": True, "message": "Proctor mode stopped"})


@proctor_bp.route("/proctor/alerts")
def proctor_alerts():
    since_id = request.args.get("since", "")
    with proctor_lock:
        alerts = list(proctor_state["alerts"])
        stats = dict(proctor_state["stats"])
        active = proctor_state["active"]
        started = proctor_state["started_at"]

    # If since_id provided, only return alerts after that id
    if since_id:
        idx = -1
        for i, a in enumerate(alerts):
            if a.get("id") == since_id:
                idx = i
                break
        if idx >= 0:
            alerts = alerts[idx + 1:]

    return jsonify({
        "active": active,
        "started_at": started,
        "stats": stats,
        "alerts": alerts[-100:],  # cap at last 100
        "total_alerts": len(proctor_state["alerts"]),
    })


@proctor_bp.route("/proctor/video_feed")
def proctor_video_feed():
    return Response(_gen_proctor_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@proctor_bp.route("/proctor/status")
def proctor_status():
    with proctor_lock:
        return jsonify({
            "active": proctor_state["active"],
            "stats": dict(proctor_state["stats"]),
            "total_alerts": len(proctor_state["alerts"]),
            "started_at": proctor_state["started_at"],
        })
