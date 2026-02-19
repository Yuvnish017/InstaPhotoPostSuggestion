# 📸 InstaPhotoPostSuggestion

**Automated Photo Curation & Suggestion Engine for Raspberry Pi**

> **TL;DR:** A Python-based automation tool that syncs photos from your phone to a Raspberry Pi, scores them based on quality and context (weather, time, composition), and sends the best "Instagram-ready" suggestions to you via a Telegram Bot.

---

## 🏗 Architecture

The system operates as a localized automation pipeline on a Raspberry Pi.

![Architecture Diagram](https://via.placeholder.com/800x400?text=Architecture+Diagram+Placeholder)

1. **Sync:** Photos are mirrored from your smartphone to a specific folder on the Raspberry Pi (via Syncthing/Resilio).
2. **Ingest:** The system scans for images available for posting, scores them, and stores metadata in SQLite DB.
3. **Score:** A logic engine analyzes images for:
   * **Quality:** Brightness, Contrast, Color Histogram.
   * **Color Dominace:** KMeans Clustering.
   * **Content:** Face Detection (OpenCV).
   * **Context:** Matches image mood to current local Weather & Time of Day.
4. **Notify:** The Telegram Bot pushes the highest-scoring image to the user.
5. **Interact:** User accepts (posts) or skips (ignores) the suggestion directly from the chat.

---

## ✨ Key Features (Phase 1)

* **📱 Auto-Sync:** Seamless one-way sync from mobile to Pi.
* **🧠 Smart Scoring:** Algorithms that prioritize photos based on lighting and "human interest" (face count).
* **🤖 Telegram Bot:** Get your photo suggestions where you spend your time.
* **☁️ Context Awareness:** Suggest "sunny" photos on sunny days.

---

## 🛠 Tech Stack

* **Hardware:** Raspberry Pi 4 (Recommended)
* **Language:** Python 3.10+
* **Computer Vision:** OpenCV (`cv2`), Pillow (`PIL`)
* **Database:** SQLite
* **APIs:**
  * [python-telegram-bot](https://python-telegram-bot.org/)
* **DevOps:** Docker (Coming Soon)

---

## 🚀 Getting Started

### Prerequisites
* Raspberry Pi with Python 3 installed.
* A Telegram Bot Token (from @BotFather).
* OpenWeatherMap API Key.

### Installation

1. **Clone the Repository**
   ```bash
   git clone [https://github.com/yourusername/InstaPhotoPostSuggestion.git](https://github.com/yourusername/InstaPhotoPostSuggestion.git)
   cd InstaPhotoPostSuggestion
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   
3. **Configuration**<br>
   Rename .env.example to .env and populate your keys<br>

### 🚀 Deployment & Execution

#### 1. Manual Run (Testing)
```bash
python main.py
```

#### 2. Running as a Background Service (Recommended)
To ensure the bot runs 24/7 and restarts on boot, use systemd.
1. Create a bash file start_insta_project.sh:
```bash
#!/bin/bash
# Path to your project folder
PROJECT_DIR=/home/pi/InstaPhotoPostSuggestion
# Path to your virtual environment activation script
VENV_ACTIVATE=$PROJECT_DIR/env/bin/activate
# Path to your main Python program
PYTHON_PROGRAM=$PROJECT_DIR/main.py

# Change directory to the project folder
cd $PROJECT_DIR

# Activate the virtual environment
source $VENV_ACTIVATE

# Execute the Python program
exec python3 $PYTHON_PROGRAM
```

2. Create the service file:
```bash
sudo nano /etc/systemd/system/instabot.service
```

3. Paste the following configuration (adjust paths to match your setup):
```toml
[Unit]
Description=My Headless Python Project for Insta Posts
After=network.target

[Service]
User=username
WorkingDirectory=/home/username/InstaPhotoPostSuggestion
# Use the shell script from Step 1
ExecStart=/home/username/start_insta_project.sh
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

4. Enable and Start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable instabot.service
sudo systemctl start instabot.service
```

5. Check status or logs:
```bash
sudo systemctl status instabot.service
# To view live logs:
journalctl -u instabot.service -f
```
   
---

## 🔮 Roadmap & Backlog

We are actively working on moving from MVP to V2.0. Here is the current development plan:

### 🚧 In Progress
* **[Infra] Docker Support:** Containerizing the application for easier deployment.
* **[Perf] Parallel Processing:** Utilizing multi-core processing for faster image scoring.

### 📋 Planned Features
* **[UX] Interactive Bot:** Add "Reject" button to Telegram messages.
* **[Algorithm] Composition Check:** "Rule of Thirds" detection to reward well-composed shots.
* **[Algorithm] Crowd Control:** Penalize scores for images with too many faces (crowds).
* **[AI] Smart Captions:** Integration with local or cloud LLMs to generate Instagram captions for approved photos.
* **[Post-Pro] Template Engine:** Auto-format approved images into 4:5 or 1:1 aspect ratios with borders.

---

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

---