from flask import Blueprint, Response, jsonify, request
import cv2, numpy as np, os, time, threading
from database import _state_lock, db
from config import KNOWN_FACES_DIR, CAMERA_SOURCES
from auth import me
try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False

face_bp = Blueprint('face', __name__)

frame_lock = threading.Lock()
camera_frames = {}
face_app = None
known_embeddings = {}


def init_face_model():
    global face_app
    if not INSIGHTFACE_AVAILABLE:
        return
    print("🤖 Loading InsightFace …")
    face_app = FaceAnalysis(name="buffalo_l",
                             providers=["CoreMLExecutionProvider","CPUExecutionProvider"])
    face_app.prepare(ctx_id=0, det_size=(640,640))
    print("✓ InsightFace ready")

def load_known_faces():
    if not (INSIGHTFACE_AVAILABLE and face_app):
        return
    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    for fname in os.listdir(KNOWN_FACES_DIR):
        if not fname.lower().endswith((".png",".jpg",".jpeg")):
            continue
        img = cv2.imread(os.path.join(KNOWN_FACES_DIR, fname))
        if img is None:
            continue
        try:
            faces = face_app.get(img)
            if faces:
                name = os.path.splitext(fname)[0]
                known_embeddings[name] = faces[0].embedding
                print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ❌ {fname}: {e}")

def cosine_dist(e1, e2):
    return 1 - np.dot(e1,e2)/(np.linalg.norm(e1)*np.linalg.norm(e2)+1e-9)

def match_face(emb):
    best, dist = None, float("inf")
    for name, ref in known_embeddings.items():
        d = cosine_dist(emb, ref)
        if d < dist:
            dist, best = d, name
    return best, dist

def liveness(f1, f2):
    if not (INSIGHTFACE_AVAILABLE and face_app):
        return True, 0.5
    try:
        fa1,fa2 = face_app.get(f1), face_app.get(f2)
        if not fa1 or not fa2:
            return False, 0.0
        lm1,lm2 = fa1[0].landmark_2d_106, fa2[0].landmark_2d_106
        if lm1 is None or lm2 is None:
            return True, 0.5
        pts=[28,30,35,40,52,64]
        ds=[np.linalg.norm(lm2[i]-lm1[i]) for i in pts if i<len(lm1)]
        avg=float(np.mean(ds)) if ds else 0.0
        return avg>1.5, avg
    except Exception:
        return True, 0.5

def capture_frame_detections(cam_id: str) -> set:
    """Capture one frame and return a set of matched student names."""
    TOLE = 0.6
    if not (INSIGHTFACE_AVAILABLE and face_app):
        return set()
    with frame_lock:
        frame = camera_frames.get(cam_id)
    if frame is None:
        return set()
    frame = frame.copy()
    try:
        faces = face_app.get(frame)
        detected = set()
        for face in faces:
            name, dist = match_face(face.embedding)
            if name and dist < TOLE:
                detected.add(name)
        return detected
    except Exception:
        return set()

def camera_loop(cam_id: str, source):
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    if not cap.isOpened():
        print(f"❌ Cannot open camera {cam_id}")
        return
    print(f"📷 Camera ready: {cam_id}")
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        if INSIGHTFACE_AVAILABLE and face_app:
            try:
                for face in face_app.get(frame):
                    x1,y1,x2,y2 = face.bbox.astype(int)
                    cv2.rectangle(frame,(x1,y1),(x2,y2),(0,200,80),2)
            except Exception:
                pass
        with frame_lock:
            camera_frames[cam_id] = frame.copy()
        time.sleep(0.03)

def gen_frames(cam_id: str):
    while True:
        with frame_lock:
            frame = camera_frames.get(cam_id)
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        time.sleep(0.04)

@face_bp.route("/cameras")
def api_cameras():
    if not me():
        return jsonify({"cameras": []}), 401
    return jsonify({"cameras": CAMERA_SOURCES})

@face_bp.route("/video_feed")
def video_feed():
    if not me():
        return Response("Unauthorised", status=401)
    cam_id = request.args.get("cam", "default")
    return Response(gen_frames(cam_id),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

