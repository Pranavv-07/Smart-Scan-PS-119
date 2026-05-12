from flask import Blueprint, request, jsonify, session
from database import db, _hash

auth_bp = Blueprint('auth', __name__)


def me():
    """Return user dict or None (never empty dict, so `if not u` works correctly)."""
    uname = session.get("username")
    if not uname:
        return None
    return db["users"].get(uname) or None

@auth_bp.route("/login", methods=["POST"])
def api_login():
    d = request.get_json(silent=True) or {}
    uname = d.get("username","").strip()
    pwd   = d.get("password","")
    user  = db["users"].get(uname)
    if not user or user["password_hash"] != _hash(pwd):
        return jsonify({"success": False, "message": "Invalid credentials"}), 401
    session.update(logged_in=True, username=uname,
                   role=user["role"], department=user.get("department"),
                   name=user.get("name",""))
    return jsonify({
        "success":    True,
        "role":       user["role"],
        "department": user.get("department"),
        "name":       user.get("name",""),
        "sections":   user.get("sections", []),
        "username":   uname,
    })

@auth_bp.route("/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})

@auth_bp.route("/check_session")
def api_check_session():
    u = me()
    if not u:
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in":  True,
        "role":       u.get("role"),
        "department": u.get("department"),
        "name":       u.get("name",""),
        "sections":   u.get("sections",[]),
        "username":   session.get("username"),
    })

