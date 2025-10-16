import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, flash
import requests
from bs4 import BeautifulSoup
from threading import Thread
import time
from flask import jsonify
from flask_cors import CORS
from pathlib import Path

# Try to load environment variables from .env files, but don't crash if it fails
try:
    from dotenv import load_dotenv

    def safe_load_env(path_str: str) -> None:
        path = Path(path_str)
        if path.exists():
            try:
                # utf-8-sig handles BOM if present
                load_dotenv(dotenv_path=str(path), encoding='utf-8-sig', override=True)
                print(f"Loaded environment from {path}")
            except Exception as e:
                print(f"Warning: Could not load env from {path}: {e}")

    # Load from common locations in order
    safe_load_env('.env')
    safe_load_env('venv/.env')
    safe_load_env('.venv/.env')
except Exception as e:
    print(f"Warning: dotenv not available or failed: {e}")
    print("Using default email configuration")

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for flash messages
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Email configuration - Use environment variables for security
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', 'your_email@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', 'your_app_password')
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))

# File to store email addresses
EMAIL_FILE = 'emails.txt'
# File to store the last scraped data to detect changes
LAST_UPDATES_FILE = 'last_updates.txt'

# --- Scraping Logic ---
def scrape_college_updates():
    url = 'https://www.cbit.ac.in/'
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return f"Error: Unable to fetch page. Status code {response.status_code}"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        updates_container = soup.find('marquee')
        
        if updates_container:
            updates = updates_container.find_all('a')
            scraped_data = []
            for update in updates:
                title = update.text.strip()
                link = update.get('href')
                scraped_data.append({'title': title, 'link': link})
            return scraped_data
        else:
            return "Could not find the marquee tag on the homepage."
            
    except requests.exceptions.RequestException as e:
        return f"Error during scraping: {e}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"

# --- Email Notification Functions ---
def send_email_notification(new_updates):
    try:
        if not os.path.exists(EMAIL_FILE):
            return
            
        with open(EMAIL_FILE, 'r') as f:
            subscribers = [email.strip() for email in f.read().splitlines() if email.strip()]

        if not subscribers:
            print("No subscribers to send emails to.")
            return

        subject = "New Updates from CBIT Website!"
        body = "Hello,\n\nThere are new updates from the college website:\n\n"
        for update in new_updates:
            body += f"- {update['title']}\n"
            
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['Subject'] = subject
        msg.attach(MIMEText(body))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_ADDRESS, subscribers, msg.as_string())

        print("Email notifications sent successfully.")
    except Exception as e:
        print(f"Error sending emails: {e}")

# --- Background Task for Monitoring Updates ---
def monitor_updates():
    while True:
        current_updates = scrape_college_updates()
        if isinstance(current_updates, list):
            last_updates_str = ""
            if os.path.exists(LAST_UPDATES_FILE):
                with open(LAST_UPDATES_FILE, 'r') as f:
                    last_updates_str = f.read()

            current_updates_str = str(current_updates)
            
            if current_updates_str != last_updates_str:
                print("New updates detected! Sending notifications.")
                send_email_notification(current_updates)
                
                with open(LAST_UPDATES_FILE, 'w') as f:
                    f.write(current_updates_str)
        
        time.sleep(3600)  # Check every hour

# --- Flask Routes ---
@app.route('/')
def home():
    updates = scrape_college_updates()
    
    if isinstance(updates, str):
        flash(updates, 'error')
        updates = []
        
    return render_template('index.html', updates=updates)

@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            if not os.path.exists(EMAIL_FILE):
                open(EMAIL_FILE, 'a').close()
            with open(EMAIL_FILE, 'r+') as f:
                subscribers = [e.strip() for e in f.read().splitlines()]
                if email not in subscribers:
                    f.write(f"{email}\n")
                    flash('You have been subscribed successfully!', 'success')
                else:
                    flash('You are already subscribed.', 'info')
            return redirect(url_for('home'))
            
    return render_template('subscribe.html')

# --- JSON API for frontend integration ---
@app.route('/api/updates')
def api_updates():
    updates = scrape_college_updates()
    if isinstance(updates, str):
        return jsonify({"error": updates}), 500
    return jsonify(updates)

@app.route('/api/subscribe', methods=['POST'])
def api_subscribe():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required"}), 400

    if not os.path.exists(EMAIL_FILE):
        open(EMAIL_FILE, 'a').close()

    with open(EMAIL_FILE, 'r+') as f:
        subscribers = [e.strip() for e in f.read().splitlines()]
        if email not in subscribers:
            f.write(f"{email}\n")
            return jsonify({"message": "Subscribed"}), 201
        else:
            return jsonify({"message": "Already subscribed"}), 200

if __name__ == '__main__':
    # Start the background monitoring thread
    monitor_thread = Thread(target=monitor_updates, daemon=True)
    monitor_thread.start()
    
    app.run(debug=True)