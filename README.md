# 🚀 QuickShare: Time-Limited File and Link Sharing Service

QuickShare is a **secure, ephemeral file and link sharing service** designed for maximum efficiency and privacy.  
It generates short, unique codes for content that **automatically expires after 5 minutes** and is permanently deleted from the server.

The project uses:
- 🐍 **Python Flask** backend for API and file handling
- 🎨 **TailwindCSS** + **Vanilla JS** frontend with responsive dark-mode UI
- 📱 **QR Code support** for easy mobile access

---

## ✨ Features
- ⏳ **Ephemeral Sharing (5-Minute TTL):** Files and links self-destruct after 5 minutes.
- 🧩 **Content Deduplication:** Same content reuses existing code if still valid.
- ⏱️ **Real-time Countdown Timer:** Live expiry countdown on frontend.
- 🔄 **Refresh Persistence:** Share code + timer persist across refresh using `localStorage`.
- 📱 **QR Code Generation:** Instantly share scannable QR codes.
- 📂 **Drag & Drop Upload:** Smooth file uploads with drag & drop.
- 🌑 **Minimalistic Dark UI:** Professional and distraction-free design.

---

## 🛠️ Installation and Setup

### 1. Clone the Repository
```bash
git clone https://github.com/keyurbhatiya/quickshare.git
cd quickshare
````

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it:

**Linux/macOS**

```bash
source venv/bin/activate
```

**Windows**

```powershell
.\venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install Flask qrcode Pillow
```

> ⚠️ Note: Pillow is a dependency of `qrcode`, but we explicitly include it.

### 4. Run the Application

```bash
python app.py
```

Now open your browser at 👉 [http://127.0.0.1:5000/](http://127.0.0.1:5000/)

---

## 🚀 Usage

### Sender:

1. Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
2. Paste text/links **OR** drag & drop a file
3. Click **"Share Content"**
4. Copy the **short code** or scan the **QR code**
5. Share with recipient

### Receiver:

1. Go to Receiver section
2. Enter the **6-digit code**
3. Click **Download**
4. Content (file/link) is served immediately 🎉

---

## ⚠️ Technical Notes

* Current backend storage uses an **in-memory Python dictionary (`storage = {}`)**.

  * ❌ Does not persist if the server restarts.
  * ✅ Works perfectly for proof-of-concept.
* For production:

  * Replace with **Redis** (ideal for TTL-based expiration)
  * Or use **NoSQL DB** like MongoDB/Firestore.
* Cleanup Task:

  * A **background thread** removes expired files every 1 minute.

---

## 👤 Author

**Developed & Maintained by:**

* [Keyur Bhatiya](https://github.com/keyurbhatiya)

📌 Connect with me:
🔗 [LinkedIn](https://linkedin.com/in/keyurbhatiya) | 🐙 [GitHub](https://github.com/keyurbhatiya) | 📸 [Instagram](https://www.instagram.com/keyur_bhatiya)

---

## 📄 License

This project is **open-source**.
Please add a suitable license (e.g., MIT, Apache 2.0) in your repo.

---

## 🌟 Show Support

If you like this project, consider giving it a ⭐ on GitHub!



---
