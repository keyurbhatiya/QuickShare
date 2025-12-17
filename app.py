import os
import sys
import time
import uuid
import shutil
import threading
import platform
import json
import requests
import qrcode
from io import BytesIO
import dotenv
from flask import Flask, request, jsonify, send_file, render_template, abort

app = Flask(__name__)

# --- Configuration ---
# Get these from your Upstash Console
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

# Validity period (5 minutes)
EXPIRATION_SECONDS = 5 * 60 

if platform.system() == "Windows":
    UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
else:
    UPLOAD_FOLDER = "/tmp/uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# --- Redis Helper (REST API) ---
def redis_set(key, value, expire_seconds):
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        print("Error: Upstash Credentials missing.", file=sys.stderr)
        return None
    
    url = f"{UPSTASH_REDIS_REST_URL}/set/{key}/{value}/EX/{expire_seconds}"
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
    try:
        response = requests.get(url, headers=headers)
        return response.json()
    except Exception as e:
        print(f"Redis Set Error: {e}", file=sys.stderr)
        return None

def redis_get(key):
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None

    url = f"{UPSTASH_REDIS_REST_URL}/get/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        if 'result' in data and data['result']:
            return json.loads(data['result'])
        return None
    except Exception as e:
        print(f"Redis Get Error: {e}", file=sys.stderr)
        return None

# --- Background Cleanup ---
def cleanup_physical_files():
    while True:
        try:
            now = time.time()
            for dirname in os.listdir(UPLOAD_FOLDER):
                dirpath = os.path.join(UPLOAD_FOLDER, dirname)
                if os.path.isdir(dirpath):
                    if now - os.path.getctime(dirpath) > EXPIRATION_SECONDS + 60:
                        shutil.rmtree(dirpath)
                elif dirname.endswith("_qr.png"):
                    if now - os.path.getctime(dirpath) > EXPIRATION_SECONDS + 60:
                        os.remove(dirpath)
        except Exception:
            pass
        time.sleep(60)

cleanup_thread = threading.Thread(target=cleanup_physical_files, daemon=True)
cleanup_thread.start()

# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/upload", methods=["POST"])
def upload():
    files_list = request.files.getlist("file")
    links_text = request.form.get("links", "").strip()

    if not (files_list and files_list[0].filename) and not links_text:
        return jsonify({"error": "No content provided."}), 400

    code = str(uuid.uuid4())[:6]
    dir_path = os.path.join(UPLOAD_FOLDER, code)
    os.makedirs(dir_path, exist_ok=True)

    file_metadata = []

    if files_list and files_list[0].filename:
        for file_obj in files_list:
            if file_obj.filename:
                filename = file_obj.filename
                filepath = os.path.join(dir_path, filename)
                file_obj.save(filepath)
                file_metadata.append({
                    "name": filename,
                    "type": "file",
                    "size": os.path.getsize(filepath)
                })

    if links_text:
        text_filename = "shared_text.txt"
        text_filepath = os.path.join(dir_path, text_filename)
        with open(text_filepath, "w") as f:
            f.write(links_text)
        file_metadata.append({
            "name": text_filename,
            "type": "text",
            "size": os.path.getsize(text_filepath)
        })

    storage_data = json.dumps({
        "files": file_metadata,
        "created_at": time.time()
    })
    
    redis_set(f"quickshare:{code}", storage_data, EXPIRATION_SECONDS)

    share_url = f"{request.url_root.rstrip('/')}/share/{code}"
    qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
    qr = qrcode.make(share_url)
    qr.save(qr_path)

    return jsonify({
        "code": code,
        "share_url": share_url,
        "qr_url": f"/qr/{code}",
        "expires_in": EXPIRATION_SECONDS
    })

@app.route("/share/<code>")
def view_shared(code):
    data = redis_get(f"quickshare:{code}")
    
    if not data:
        return render_template("error.html", message="This link has expired or is invalid."), 404

    return render_template("download.html", 
                           code=code, 
                           files=data['files'], 
                           created_at=data['created_at'], 
                           ttl=EXPIRATION_SECONDS)

@app.route("/download/<code>/<filename>")
def download_file(code, filename):
    data = redis_get(f"quickshare:{code}")
    if not data:
        abort(404, description="Link expired")

    file_path = os.path.join(UPLOAD_FOLDER, code, filename)
    if not os.path.exists(file_path):
        abort(404, description="File not found on server")

    return send_file(file_path, as_attachment=True)

@app.route("/qr/<code>")
def get_qr(code):
    qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
    if os.path.exists(qr_path):
        return send_file(qr_path, mimetype="image/png")
    return "QR not found", 404

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)