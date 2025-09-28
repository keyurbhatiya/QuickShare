from flask import Flask, request, jsonify, send_file, render_template
import os, uuid, qrcode
import sys
import time
import hashlib
import threading

app = Flask(__name__)

# --- Configuration ---
UPLOAD_FOLDER = "uploads" 
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 5 minutes validity
EXPIRATION_SECONDS = 5 * 60 
CLEANUP_INTERVAL_SECONDS = 60 # Check for expired files every minute

# --- Data Structures (CRITICAL: In-memory store) ---
# For a production application, this MUST be replaced by a persistent store (e.g., Redis, Firestore).
# { "code": { "filepath": ..., "timestamp": ..., "hash": ..., "filename": ... } }
storage = {} 
# Reverse lookup for deduplication: { "hash": "code" }
hash_to_code = {}

# -------------------------------
# Core Logic: Content Hashing
# -------------------------------
def get_content_hash(content, is_file=False):
    """Calculates SHA256 hash for deduplication."""
    hasher = hashlib.sha256()
    
    if is_file:
        # File object needs chunk reading (safer for large files)
        while True:
            chunk = content.read(4096)
            if not chunk:
                break
            hasher.update(chunk)
        # Reset pointer for file saving later
        content.seek(0)
    else:
        # Text/Link content
        hasher.update(content.encode('utf-8'))
        
    return hasher.hexdigest()

# -------------------------------
# Core Logic: Cleanup Thread
# -------------------------------
def cleanup_expired_files():
    """Periodically removes expired files and data from storage/disk."""
    
    # Use a list of codes to delete to avoid modifying dict while iterating
    codes_to_delete = []
    
    for code, data in storage.items():
        if time.time() - data['timestamp'] > EXPIRATION_SECONDS:
            codes_to_delete.append(code)

    for code in codes_to_delete:
        try:
            data = storage[code]
            
            # 1. Delete the actual file/link content
            if os.path.exists(data['filepath']):
                os.remove(data['filepath'])
            
            # 2. Delete the QR code image
            qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
            if os.path.exists(qr_path):
                os.remove(qr_path)
            
            # 3. Remove from in-memory stores
            del hash_to_code[data['hash']]
            del storage[code]
            print(f"Cleanup: Deleted expired content for code {code}", file=sys.stderr)
            
        except Exception as e:
            # Log any deletion error but continue cleanup
            print(f"Error during cleanup for code {code}: {e}", file=sys.stderr)
    
    # Reschedule the thread to run again
    threading.Timer(CLEANUP_INTERVAL_SECONDS, cleanup_expired_files).start()

# Start the cleanup thread immediately upon startup
# The thread is set as daemon so it won't prevent the main app from exiting
cleanup_thread = threading.Thread(target=cleanup_expired_files, daemon=True)
cleanup_thread.start()


# -------------------------------
# Home Page (Frontend)
# -------------------------------
@app.route("/")
def index():
    """Serves the main frontend HTML file."""
    return render_template("index.html")

# -------------------------------
# API: Upload (Links or File)
# -------------------------------
@app.route("/api/upload", methods=["POST"])
def upload():
    """Handles uploads, checks for duplication, and sets expiration."""
    
    links = request.form.get("links", "").strip()
    file_obj = request.files.get("file")
    
    filepath = None
    file_hash = None
    original_filename = None
    
    # 1. Determine content hash and check for existing content
    if file_obj and file_obj.filename:
        original_filename = file_obj.filename
        file_hash = get_content_hash(file_obj, is_file=True)
    elif links:
        original_filename = "Links_or_Text"
        file_hash = get_content_hash(links, is_file=False)
    else:
        return jsonify({"error": "Please provide either links/text or select a file to upload."}), 400

    # Check for duplication (same content uploaded recently)
    if file_hash in hash_to_code:
        code = hash_to_code[file_hash]
        data = storage[code]
        
        # If the existing entry is still valid, reuse it
        if time.time() - data['timestamp'] < EXPIRATION_SECONDS:
            print(f"Deduplication: Reusing code {code} for identical content.", file=sys.stderr)
            return jsonify({
                "message": "Content already uploaded. Reusing code.",
                "code": code,
                "download_url": f"/api/download?code={code}",
                "qr_code": f"/qr/{code}",
                "timestamp": data['timestamp'],
                "expires_in": EXPIRATION_SECONDS
            })

    # 2. Generate new code and save content
    code = str(uuid.uuid4())[:6] 
    
    if file_obj and file_obj.filename:
        filename_on_disk = f"{code}_{original_filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename_on_disk)
        # file_obj pointer was reset in get_content_hash, now save it
        file_obj.save(filepath)
    elif links:
        filename_on_disk = f"{code}_links.txt"
        filepath = os.path.join(UPLOAD_FOLDER, filename_on_disk)
        with open(filepath, "w") as f:
            f.write(links)

    # 3. Store data
    current_time = time.time()
    storage[code] = {
        "filepath": filepath,
        "timestamp": current_time,
        "hash": file_hash,
        "filename": original_filename
    }
    hash_to_code[file_hash] = code # Update hash lookup

    # 4. Generate QR code (using request.url_root for shareability)
    download_link_public = f"{request.url_root.rstrip('/')}/api/download?code={code}"
    qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
    try:
        qr = qrcode.make(download_link_public)
        qr.save(qr_path)
    except Exception as e:
        print(f"QR Code generation failed for code {code}: {e}", file=sys.stderr)
        qr_path = None # Indicate failure

    # 5. Return success response
    return jsonify({
        "message": "Content uploaded successfully.",
        "code": code,
        "download_url": f"/api/download?code={code}", 
        "qr_code": f"/qr/{code}" if qr_path else None,
        "timestamp": current_time,
        "expires_in": EXPIRATION_SECONDS
    })

# -------------------------------
# API: Download (by Code)
# -------------------------------
@app.route("/api/download", methods=["GET"])
def download():
    """Serves the file if the code is valid and not expired."""
    code = request.args.get("code")
    
    if not code or code not in storage:
        return jsonify({"error": "Invalid or expired code. Content not found."}), 404
    
    data = storage[code]
    
    # Check for expiration
    if time.time() - data['timestamp'] > EXPIRATION_SECONDS:
        # If expired but not yet cleaned up by the thread, immediately clean it up
        try:
            del hash_to_code[data['hash']]
            del storage[code]
            if os.path.exists(data['filepath']):
                os.remove(data['filepath'])
            qr_path = os.path.join(UPLOAD_FOLDER, f"{code}_qr.png")
            if os.path.exists(qr_path):
                os.remove(qr_path)
        except Exception:
            pass # Ignore cleanup errors
            
        return jsonify({"error": "The download link has expired. Please re-upload the content."}), 410 # 410 Gone
    
    filepath = data['filepath']
    
    if not os.path.exists(filepath):
        # File is missing on disk but in memory (shouldn't happen, but good check)
        return jsonify({"error": "File not found on server (server error). Please try again."}), 500
        
    return send_file(filepath, as_attachment=True, download_name=data['filename'])

# -------------------------------
# Serve QR Code
# -------------------------------
@app.route("/qr/<code>")
def get_qr(code):
    """Serves the generated QR code image."""
    # Check for code validity/existence before serving QR
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
