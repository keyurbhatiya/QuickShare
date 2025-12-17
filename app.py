import os
import sys
import time
import uuid
import json
import requests
import qrcode
import base64
from io import BytesIO
import dotenv
from flask import Flask, request, jsonify, send_file, render_template, abort

app = Flask(__name__)

# --- Configuration ---
# Get these from your Vercel Settings -> Environment Variables
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

# Validity period (5 minutes)
EXPIRATION_SECONDS = 5 * 60 
# Max size for Upstash Free Tier (approx 1MB safe limit)
MAX_PAYLOAD_SIZE = 1024 * 1024 

# --- Redis Helper (REST API) ---
def redis_set(key, value, expire_seconds):
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        print("Error: Upstash Credentials missing.", file=sys.stderr)
        return None
    
    # We use a POST request here because the payload (files) might be large
    url = f"{UPSTASH_REDIS_REST_URL}/set/{key}?EX={expire_seconds}"
    headers = {
        "Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}",
        "Content-Type": "text/plain" 
    }
    try:
        response = requests.post(url, headers=headers, data=value)
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

    file_metadata = []
    total_size = 0

    # 1. Process Files (Convert to Base64 for Redis storage)
    if files_list and files_list[0].filename:
        for file_obj in files_list:
            if file_obj.filename:
                file_content = file_obj.read()
                size = len(file_content)
                total_size += size
                
                if total_size > MAX_PAYLOAD_SIZE:
                    return jsonify({"error": "Total size exceeds 1MB limit (Vercel/Redis Limit)."}), 413

                # Encode content to base64 string to store in JSON
                encoded_content = base64.b64encode(file_content).decode('utf-8')
                
                file_metadata.append({
                    "name": file_obj.filename,
                    "type": "file",
                    "size": size,
                    "content": encoded_content 
                })

    # 2. Process Text
    if links_text:
        encoded_text = base64.b64encode(links_text.encode('utf-8')).decode('utf-8')
        size = len(links_text)
        total_size += size
        
        if total_size > MAX_PAYLOAD_SIZE:
             return jsonify({"error": "Total size exceeds 1MB limit."}), 413

        file_metadata.append({
            "name": "shared_text.txt",
            "type": "text",
            "size": size,
            "content": encoded_text
        })

    # 3. Save to Redis
    code = str(uuid.uuid4())[:6]
    
    storage_data = json.dumps({
        "files": file_metadata,
        "created_at": time.time()
    })
    
    # Store in Redis
    result = redis_set(f"quickshare:{code}", storage_data, EXPIRATION_SECONDS)
    
    if not result:
        return jsonify({"error": "Database connection failed."}), 500

    share_url = f"{request.url_root.rstrip('/')}/share/{code}"
    
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

    # We don't send the full content to the frontend, just metadata
    # The template expects 'files' list with 'name' and 'size'
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

    # Find the specific file in the list
    target_file = None
    for f in data['files']:
        if f['name'] == filename:
            target_file = f
            break
            
    if not target_file:
        abort(404, description="File not found")

    # Decode base64 content back to bytes
    try:
        file_bytes = base64.b64decode(target_file['content'])
        return send_file(
            BytesIO(file_bytes),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return abort(500, description="Error decoding file")

@app.route("/qr/<code>")
def get_qr(code):
    # On Vercel, we can't save the QR to disk. We generate it on the fly.
    share_url = f"{request.url_root.rstrip('/')}/share/{code}"
    img = qrcode.make(share_url)
    
    memory_file = BytesIO()
    img.save(memory_file, 'PNG')
    memory_file.seek(0)
    
    return send_file(memory_file, mimetype="image/png")

# For local testing only
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)