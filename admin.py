from flask import Blueprint, jsonify, request, Response, send_file
import csv, io, os
from database import db, CSV_FILE
from config import DEPARTMENTS
from auth import me

admin_bp = Blueprint('admin', __name__)


@admin_bp.route("/admin/all_users")
def admin_all_users():
    u = me()
    if not u or u["role"] != "admin":
        return jsonify({"error":"Forbidden"}),403
    users = [
        {"username": un, **{k:v for k,v in ud.items() if k!="password_hash"}}
        for un, ud in db["users"].items()
    ]
    return jsonify({"users": users, "departments": DEPARTMENTS})

@admin_bp.route("/admin/export_csv")
def admin_export_csv():
    u = me()
    if not u or u["role"] not in ("admin","dept_head"):
        return Response("Forbidden",status=403)
    section = request.args.get("section","")
    dept    = u["department"] if u["role"]=="dept_head" else request.args.get("dept","")

    out_rows = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if section and row.get("Section")!=section:
                    continue
                if dept and row.get("Department")!=dept:
                    continue
                out_rows.append(row)

    out = io.StringIO()
    if out_rows:
        w = csv.DictWriter(out, fieldnames=out_rows[0].keys())
        w.writeheader(); w.writerows(out_rows)
    fname = f"attendance_{section or dept or 'all'}.csv"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})
