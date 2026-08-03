"""
app_dev.py — גרסת פיתוח מקומית, בלי AWS בכלל.

- בלי Cognito: /admin פתוח ישירות, אין login/logout אמיתיים.
- בלי DynamoDB: המידע נשמר בזיכרון + מסונכרן לקובץ dev_data.json
  לצידך (כך שלא תאבד נתונים כשתעצור ותפעיל את השרת מחדש).

הרצה:
    python app_dev.py
ואז פתח:
    http://localhost:5000/admin   (בלי login)
    http://localhost:5000/c/<couple_id>   (עמוד האורח)

כשתעבור בהמשך לגרסה האמיתית מול AWS, פשוט תריץ app.py הרגיל
עם משתני הסביבה של Cognito/DynamoDB - הלוגיקה זהה.
"""

import os
import csv
import io
import re
import json
import uuid
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_file

app = Flask(__name__)
app.secret_key = "dev-secret-key-not-for-production"

DATA_FILE = os.path.join(os.path.dirname(__file__), "dev_data.json")


def _load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"couples": {}, "rsvps": []}


def _save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_DATA, f, ensure_ascii=False, indent=2)


_DATA = _load_data()


# ---- "מדומה DynamoDB" בזיכרון (רק בשביל app_dev.py) ----

def couples_scan():
    return list(_DATA["couples"].values())


def couples_get(couple_id):
    return _DATA["couples"].get(couple_id)


def couples_put(item):
    _DATA["couples"][item["couple_id"]] = item
    _save_data()


def rsvp_put(item):
    _DATA["rsvps"].append(item)
    _save_data()


def rsvp_scan_by_couple(couple_id):
    return [r for r in _DATA["rsvps"] if r.get("couple_id") == couple_id]


# ---- login מדומה: תמיד "מחובר" ב-DEV_MODE ----

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session.setdefault("user", {"email": "dev@local"})
        return f(*args, **kwargs)
    return decorated


@app.route("/login")
def login():
    session["user"] = {"email": "dev@local"}
    return redirect(url_for("admin"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("admin"))


def make_couple_id(groom_name, bride_name):
    base = f"{groom_name}-{bride_name}".strip().lower()
    base = re.sub(r"\s+", "-", base)
    base = re.sub(r"[^a-zA-Z0-9\u0590-\u05FF-]", "", base)
    return f"{base}-{str(uuid.uuid4())[:6]}"


@app.route("/")
def root():
    return redirect(url_for("admin"))


@app.route("/admin")
@login_required
def admin():
    couples = couples_scan()
    couples = sorted(couples, key=lambda x: x.get("created_at", ""), reverse=True)
    message = request.args.get("message")
    return render_template("admin.html", couples=couples, message=message)


@app.route("/admin/create-couple", methods=["POST"])
def create_couple():
    groom_name = request.form.get("groom_name", "").strip()
    bride_name = request.form.get("bride_name", "").strip()
    venue_name = request.form.get("venue_name", "").strip()
    event_date = request.form.get("event_date", "").strip()
    event_day = request.form.get("event_day", "").strip()
    reception_time = request.form.get("reception_time", "").strip()
    ceremony_time = request.form.get("ceremony_time", "").strip()

    if not groom_name or not bride_name or not venue_name or not event_date:
        return redirect(url_for("admin", message="חסרים פרטים חובה ליצירת זוג."))

    couple_id = make_couple_id(groom_name, bride_name)

    couples_put({
        "couple_id": couple_id,
        "groom_name": groom_name,
        "bride_name": bride_name,
        "venue_name": venue_name,
        "event_date": event_date,
        "event_day": event_day,
        "reception_time": reception_time,
        "ceremony_time": ceremony_time,
        "created_at": str(uuid.uuid4())
    })
    return redirect(url_for("admin", message="הזוג נוצר בהצלחה."))


@app.route("/c/<couple_id>")
def couple_page(couple_id):
    couple = couples_get(couple_id)
    if not couple:
        return "Couple page not found", 404
    return render_template("index.html", couple=couple)


@app.route("/submit/<couple_id>", methods=["POST"])
def submit(couple_id):
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    name = data.get("name")
    phone = data.get("phone")
    guests = data.get("guests")
    attendance = data.get("attendance")
    meal = data.get("meal", "")

    if not all([name, phone, guests, attendance]):
        return jsonify({"error": "Missing required fields"}), 400

    rsvp_put({
        "couple_id": str(couple_id),
        "phone": str(phone),
        "name": str(name),
        "guests": int(guests),
        "attendance": str(attendance),
        "attending": attendance == "yes",
        "meal": str(meal)
    })
    return jsonify({"message": "RSVP saved successfully"}), 200


@app.route("/admin/download/<couple_id>")
def download_csv(couple_id):
    items = rsvp_scan_by_couple(couple_id)

    output = io.StringIO()
    output.write("\ufeff")

    writer = csv.writer(output)
    writer.writerow(["name", "phone", "guests", "attendance", "attending", "meal"])
    for item in items:
        writer.writerow([
            item.get("name", ""),
            item.get("phone", ""),
            item.get("guests", ""),
            item.get("attendance", ""),
            item.get("attending", ""),
            item.get("meal", "")
        ])

    bytes_output = io.BytesIO(output.getvalue().encode("utf-8"))
    bytes_output.seek(0)
    output.close()

    return send_file(
        bytes_output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{couple_id}_rsvp.csv"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

