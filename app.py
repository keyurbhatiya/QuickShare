from flask import Flask, request, jsonify, send_file, render_template
import os, uuid, qrcode
import sys
import time
import hashlib
import threading
import platform
import shutil
from io import BytesIO
import zipfile

app = Flask(__name__)

# --- Configuration ---
if platform.system() == "Windows":
    # Use local project folder on Windows
    UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
else:
    # Use /tmp/uploads on Linux (Render)
    UPLOAD_FOLDER = "/tmp/uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# 5 minutes validity
EXPIRATION_SECONDS = 5 * 60 
CLEANUP_INTERVAL_SECONDS = 60 # Check for expired files every minute

# --- Data Structures (CRITICAL: In-memory store) ---
# For a production application, this MUST be replaced by a persistent store (e.g., Redis, Firestore).
# { 
#   "code": { 
#       "dirpath": ..., 
#       "timestamp": ..., 
#       "files": [ {"filename": ..., "filesize": ...}, ... ], # List of files/text items
#       "content_type": "files" or "text" or "mixed" 
#   } 
# }
storage = {} 

# -------------------------------
# Core Logic: Cleanup Thread
# -------------------------------
def cleanup_expired_files():
    """Periodically removes expired file directories, data, and QR codes."""
    
    codes_to_delete = []
    
    for code, data in storage.items():
        if time.time() - data['timestamp'] > EXPIRATION_SECONDS:
            codes_to_delete.append(code)

    for code in codes_to_delete:
        try:
            data = storage.pop(code, None)
            if data:
                # 1. Delete the entire content directory (which includes all files)
                if os.path.exists(data['dirpath']):
                    shutil.rmtree(data['dirpath'])
                
                # 2. Delete the QR code image
                qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
                if os.path.exists(qr_path):
                    os.remove(qr_path)
                
                print(f"Cleanup: Deleted expired content for code {code}", file=sys.stderr)
            
        except Exception as e:
            # Log any deletion error but continue cleanup
            print(f"Error during cleanup for code {code}: {e}", file=sys.stderr)
    
    # Reschedule the thread to run again
    threading.Timer(CLEANUP_INTERVAL_SECONDS, cleanup_expired_files).start()

# Start the cleanup thread immediately upon startup
cleanup_thread = threading.Thread(target=cleanup_expired_files, daemon=True)
cleanup_thread.start()


# -------------------------------
# Home Page (Frontend)
# -------------------------------
@app.route("/")
def index():
    """Serves the main frontend HTML file."""
    # We pass the expiration time to the frontend for countdown logic consistency
    return render_template("index.html", expiration_seconds=EXPIRATION_SECONDS)

# -------------------------------
# API: Upload (Multiple Files and/or Text/Links)
# -------------------------------
@app.route("/api/upload", methods=["POST"])
def upload():
    """Handles uploads, saves content to a unique directory, and sets expiration."""
    
    files_list = request.files.getlist("file")
    links_text = request.form.get("links", "").strip()
    
    if not (files_list and files_list[0].filename) and not links_text:
        return jsonify({"error": "Please provide files or paste links/text to share."}), 400

    # 1. Generate new unique code and directory
    code = str(uuid.uuid4())[:6] 
    dir_path = os.path.join(UPLOAD_FOLDER, code)
    os.makedirs(dir_path, exist_ok=True)
    
    saved_files_metadata = []
    
    # 2. Save file uploads (if any)
    content_type = ""
    
    if files_list and files_list[0].filename:
        content_type = "files"
        for file_obj in files_list:
            if file_obj.filename:
                # Use a simpler filename on disk, but store original for download
                filename_on_disk = file_obj.filename
                filepath = os.path.join(dir_path, filename_on_disk)
                file_obj.save(filepath)
                saved_files_metadata.append({
                    "filename": filename_on_disk,
                    "filepath": filepath,
                    "filesize": os.path.getsize(filepath)
                })

    # 3. Save links/text as a file (if any)
    if links_text:
        if content_type == "files":
            content_type = "mixed"
        else:
            content_type = "text"
            
        text_filename = "quickshare_text_or_links.txt"
        text_filepath = os.path.join(dir_path, text_filename)
        with open(text_filepath, "w") as f:
            f.write("--- Content shared via QuickShare ---\n\n")
            f.write(links_text)
            
        saved_files_metadata.append({
            "filename": text_filename,
            "filepath": text_filepath,
            "filesize": os.path.getsize(text_filepath)
        })

    # 4. Check for deduplication (only for exact single file or text content)
    # NOTE: Deduplication for multiple files is skipped for complexity/risk reasons 
    # and given the short expiration time.
    
    # 5. Store data
    current_time = time.time()
    storage[code] = {
        "dirpath": dir_path,
        "timestamp": current_time,
        "files": saved_files_metadata,
        "content_type": content_type,
        "expires_in": EXPIRATION_SECONDS
    }

    # 6. Generate QR code
    download_link_public = f"{request.url_root.rstrip('/')}/api/download?code={code}"
    qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
    try:
        qr = qrcode.make(download_link_public)
        qr.save(qr_path)
    except Exception as e:
        print(f"QR Code generation failed for code {code}: {e}", file=sys.stderr)
        qr_path = None 

    # 7. Return success response
    return jsonify({
        "message": "Content uploaded successfully.",
        "code": code,
        "download_url": f"/api/download?code={code}", 
        "qr_code": f"/qr/{code}" if qr_path else None,
        "timestamp": current_time,
        "expires_in": EXPIRATION_SECONDS,
        "files": [f['filename'] for f in saved_files_metadata]
    })

# -------------------------------
# API: Download (by Code)
# -------------------------------
@app.route("/api/download", methods=["GET"])
def download():
    """Serves all shared content as a ZIP file if the code is valid and not expired."""
    code = request.args.get("code")
    
    if not code or code not in storage:
        return jsonify({"error": "Invalid or expired code. Content not found."}), 404
    
    data = storage[code]
    
    # Check for expiration
    if time.time() - data['timestamp'] > EXPIRATION_SECONDS:
        # Perform immediate cleanup if expired
        try:
            if os.path.exists(data['dirpath']):
                shutil.rmtree(data['dirpath'])
            qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
            if os.path.exists(qr_path):
                os.remove(qr_path)
            del storage[code]
        except Exception:
            pass 
            
        return jsonify({"error": "The download link has expired. Please re-upload the content."}), 410 
    
    # --- Create In-Memory ZIP File ---
    memory_file = BytesIO()
    zip_filename = f"QuickShare_{code}.zip"
    
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        dir_path = data['dirpath']
        
        if not os.path.exists(dir_path):
             return jsonify({"error": "Content directory missing on server (server error). Please try again."}), 500

        for item in data['files']:
            file_path = item['filepath']
            # Only add the file to the ZIP if it exists
            if os.path.exists(file_path):
                 # Add file using the original filename as the name inside the ZIP
                 zf.write(file_path, arcname=item['filename'])
            else:
                print(f"File missing on disk: {file_path}", file=sys.stderr)

    # Rewind the in-memory file to the start for sending
    memory_file.seek(0)
    
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_filename
    )

# -------------------------------
# Serve QR Code
# -------------------------------
@app.route("/qr/<code>")
def get_qr(code):
    """Serves the generated QR code image."""
    if code not in storage:
        return jsonify({"error": "QR code not found or expired."}), 404
        
    qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
    if not os.path.exists(qr_path):
        return jsonify({"error": "QR code file missing on server."}), 404
    return send_file(qr_path, mimetype="image/png")

# -------------------------------
# Run App
# -------------------------------
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
