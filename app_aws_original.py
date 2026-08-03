import os
import csv
import io
import re
import uuid
import boto3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, jsonify, session, send_file
from authlib.integrations.flask_client import OAuth
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr


app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
COUPLES_TABLE_NAME = os.environ.get("COUPLES_TABLE", "RSVP_Couples")
RSVP_TABLE_NAME = os.environ.get("RSVP_TABLE", "RSVP_Responses")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
couples_table = dynamodb.Table(COUPLES_TABLE_NAME)
rsvp_table = dynamodb.Table(RSVP_TABLE_NAME)

COGNITO_USER_POOL_ID  = os.environ.get("COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID     = os.environ.get("COGNITO_CLIENT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET")
COGNITO_DOMAIN        = os.environ.get("COGNITO_DOMAIN")
APP_BASE_URL          = os.environ.get("APP_BASE_URL", "http://localhost:5000")

oauth = OAuth(app)
oauth.register(
    name="oidc",
    authority=f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}",
    client_id=COGNITO_CLIENT_ID,
    client_secret=COGNITO_CLIENT_SECRET,
    server_metadata_url=(
        f"https://cognito-idp.{AWS_REGION}.amazonaws.com"
        f"/{COGNITO_USER_POOL_ID}/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email"},
)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login")
def login():
    redirect_uri = f"{APP_BASE_URL}/authorize"
    return oauth.oidc.authorize_redirect(redirect_uri)


@app.route("/authorize")
def authorize():
    token = oauth.oidc.authorize_access_token()
    session["user"] = token["userinfo"]
    return redirect(url_for("admin"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    logout_url = (
        f"{COGNITO_DOMAIN}/logout"
        f"?client_id={COGNITO_CLIENT_ID}"
        f"&logout_uri={APP_BASE_URL}/login"
    )
    return redirect(logout_url)


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
    try:
        response = couples_table.scan()
        couples = response.get("Items", [])
        couples = sorted(couples, key=lambda x: x.get("created_at", ""), reverse=True)
    except ClientError as e:
        app.logger.error("DynamoDB error: %s", e.response["Error"]["Message"])
        couples = []

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

    try:
        couples_table.put_item(
            Item={
                "couple_id": couple_id,
                "groom_name": groom_name,
                "bride_name": bride_name,
                "venue_name": venue_name,
                "event_date": event_date,
                "event_day": event_day,
                "reception_time": reception_time,
                "ceremony_time": ceremony_time,
                "created_at": str(uuid.uuid4())
            }
        )
        return redirect(url_for("admin", message="הזוג נוצר בהצלחה."))
    except ClientError as e:
        app.logger.error("DynamoDB error: %s", e.response["Error"]["Message"])
        return redirect(url_for("admin", message="שגיאה ביצירת הזוג."))


@app.route("/c/<couple_id>")
def couple_page(couple_id):
    try:
        response = couples_table.get_item(Key={"couple_id": couple_id})
        couple = response.get("Item")
    except ClientError as e:
        app.logger.error("DynamoDB error: %s", e.response["Error"]["Message"])
        couple = None

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

    try:
        rsvp_table.put_item(
            Item={
                "couple_id": str(couple_id),
                "phone": str(phone),
                "name": str(name),
                "guests": int(guests),
                "attendance": str(attendance),
                "attending": attendance == "yes",
                "meal": str(meal)
            }
        )

        return jsonify({"message": "RSVP saved successfully"}), 200

    except ClientError as e:
        app.logger.error("DynamoDB error: %s", e.response["Error"]["Message"])
        return jsonify({"error": "Could not save RSVP. Please try again later."}), 500


@app.route("/admin/download/<couple_id>")
def download_csv(couple_id):
    try:
        response = rsvp_table.scan(
            FilterExpression=Attr("couple_id").eq(couple_id)
        )
        items = response.get("Items", [])
    except ClientError as e:
        app.logger.error("DynamoDB error: %s", e.response["Error"]["Message"])
        items = []

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
    app.run(host="0.0.0.0", port=5000, debug=False)
