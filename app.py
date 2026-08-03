"""
app.py — גרסת ביניים: DynamoDB אמיתי, אבל עדיין בלי Cognito.

- בלי Cognito: /admin פתוח ישירות, אין login/logout אמיתיים (כמו קודם).
- עם DynamoDB אמיתי: המידע נשמר בענן, בטבלאות RSVP_Couples ו-RSVP_Responses
  שנוצרו דרך Terraform.

דרישה מקדימה: `aws configure` כבר הוגדר על המחשב הזה (עשינו את זה קודם),
ו-Terraform כבר יצר את שתי הטבלאות ב-AWS.

הרצה:
    python app.py
ואז פתח:
    http://localhost:5000/admin   (בלי login)
"""

import os
import csv
import io
import re
import uuid
import boto3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_file
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

app = Flask(__name__)
app.secret_key = "dev-secret-key-not-for-production"

# ---- חיבור אמיתי ל-DynamoDB ----
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
COUPLES_TABLE_NAME = os.environ.get("COUPLES_TABLE", "RSVP_Couples")
RSVP_TABLE_NAME = os.environ.get("RSVP_TABLE", "RSVP_Responses")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
couples_table = dynamodb.Table(COUPLES_TABLE_NAME)
rsvp_table = dynamodb.Table(RSVP_TABLE_NAME)


# ---- פונקציות הגישה ל-DB - עכשיו מדברות עם DynamoDB אמיתי ----

def couples_scan():
    try:
        response = couples_table.scan()
        return response.get("Items", [])
    except ClientError as e:
        app.logger.error("DynamoDB error (couples_scan): %s", e.response["Error"]["Message"])
        return []


def couples_get(couple_id):
    try:
        response = couples_table.get_item(Key={"couple_id": couple_id})
        return response.get("Item")
    except ClientError as e:
        app.logger.error("DynamoDB error (couples_get): %s", e.response["Error"]["Message"])
        return None


def couples_put(item):
    try:
        couples_table.put_item(Item=item)
        return True
    except ClientError as e:
        app.logger.error("DynamoDB error (couples_put): %s", e.response["Error"]["Message"])
        return False


def rsvp_put(item):
    try:
        rsvp_table.put_item(Item=item)
        return True
    except ClientError as e:
        app.logger.error("DynamoDB error (rsvp_put): %s", e.response["Error"]["Message"])
        return False


def rsvp_scan_by_couple(couple_id):
    # query, not scan: יעיל בהרבה כי couple_id הוא ה-partition key של הטבלה
    try:
        response = rsvp_table.query(
            KeyConditionExpression=Key("couple_id").eq(couple_id)
        )
        return response.get("Items", [])
    except ClientError as e:
        app.logger.error("DynamoDB error (rsvp_scan_by_couple): %s", e.response["Error"]["Message"])
        return []


# ---- login מדומה: תמיד "מחובר" (בלי Cognito, עדיין) ----

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

    ok = couples_put({
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

    if ok:
        return redirect(url_for("admin", message="הזוג נוצר בהצלחה."))
    return redirect(url_for("admin", message="שגיאה ביצירת הזוג."))


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

    ok = rsvp_put({
        "couple_id": str(couple_id),
        "phone": str(phone),
        "name": str(name),
        "guests": int(guests),
        "attendance": str(attendance),
        "attending": attendance == "yes",
        "meal": str(meal)
    })

    if ok:
        return jsonify({"message": "RSVP saved successfully"}), 200
    return jsonify({"error": "Could not save RSVP. Please try again later."}), 500


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
