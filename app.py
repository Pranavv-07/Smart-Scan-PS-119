from flask import Flask, send_file
from config import SECRET_KEY, GOOGLE_API_KEY
import google.generativeai as genai

from database import setup_csv
from face_service import init_face_model, load_known_faces, camera_frames, frame_lock

from auth import auth_bp
from face_service import face_bp
from faculty import faculty_bp
from dept import dept_bp
from admin import admin_bp
from proctor_engine import proctor_bp

app = Flask(__name__)
genai.configure(api_key=GOOGLE_API_KEY)
app.secret_key = SECRET_KEY

app.register_blueprint(auth_bp)
app.register_blueprint(face_bp)
app.register_blueprint(faculty_bp)
app.register_blueprint(dept_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(proctor_bp)

@app.route("/")
def index():
    return send_file("index.html")

setup_csv()
init_face_model()
load_known_faces()

from proctor_engine import init_proctor
init_proctor()

import threading
from face_service import camera_loop
from config import CAMERA_SOURCES

# Start cameras
for cam in CAMERA_SOURCES:
    camera_frames[cam["id"]] = None
    threading.Thread(target=camera_loop, args=(cam["id"],cam["source"]), daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
