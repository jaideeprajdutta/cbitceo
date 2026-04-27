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
import psycopg2
from psycopg2.extras import RealDictCursor
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for flash messages
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Initialize the database tables."""
    if not DATABASE_URL:
        print("DATABASE_URL not set - using file-based storage fallback")
        return False
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS last_updates (
                id INTEGER PRIMARY KEY DEFAULT 1,
                data TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Insert default row if not exists
        cur.execute('INSERT INTO last_updates (id, data) VALUES (1, %s) ON CONFLICT (id) DO NOTHING', (str([]),))
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully")
        return True
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return False

# Initialize database on startup
db_available = init_db()

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
def get_subscribers():
    """Get all subscribers from database or file fallback."""
    if db_available:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('SELECT email FROM subscribers')
            subscribers = [row['email'] for row in cur.fetchall()]
            cur.close()
            conn.close()
            return subscribers
        except Exception as e:
            print(f"DB error getting subscribers: {e}")
    # Fallback to file
    if os.path.exists(EMAIL_FILE):
        with open(EMAIL_FILE, 'r') as f:
            return [email.strip() for email in f.read().splitlines() if email.strip()]
    return []

def save_subscriber(email):
    """Save subscriber to database or file fallback."""
    if db_available:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO subscribers (email) VALUES (%s) ON CONFLICT (email) DO NOTHING',
                (email,)
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"DB error saving subscriber: {e}")
    # Fallback to file
    if not os.path.exists(EMAIL_FILE):
        open(EMAIL_FILE, 'a').close()
    with open(EMAIL_FILE, 'r+') as f:
        subscribers = [e.strip() for e in f.read().splitlines()]
        if email not in subscribers:
            f.write(f"{email}\n")
            return True
    return False

def send_email_notification(new_updates):
    try:
        subscribers = get_subscribers()

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

# --- Database helpers for persistent state ---
def get_last_updates():
    if db_available:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('SELECT data FROM last_updates WHERE id = 1')
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row['data'] if row else "[]"
        except Exception as e:
            print(f"DB error getting last updates: {e}")
    # Fallback to file
    if os.path.exists(LAST_UPDATES_FILE):
        with open(LAST_UPDATES_FILE, 'r') as f:
            return f.read()
    return "[]"

def save_last_updates(data):
    if db_available:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO last_updates (id, data, updated_at) VALUES (1, %s, CURRENT_TIMESTAMP) '
                'ON CONFLICT (id) DO UPDATE SET data = %s, updated_at = CURRENT_TIMESTAMP',
                (data, data)
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"DB error saving last updates: {e}")
    # Fallback to file
    with open(LAST_UPDATES_FILE, 'w') as f:
        f.write(data)
    return True

# --- Background Task for Monitoring Updates ---
def monitor_updates():
    while True:
        current_updates = scrape_college_updates()
        if isinstance(current_updates, list):
            last_updates_str = get_last_updates()
            current_updates_str = str(current_updates)

            if current_updates_str != last_updates_str:
                print("New updates detected! Sending notifications.")
                send_email_notification(current_updates)
                save_last_updates(current_updates_str)

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
            if save_subscriber(email):
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

    if save_subscriber(email):
        return jsonify({"message": "Subscribed"}), 201
    else:
        return jsonify({"message": "Already subscribed"}), 200

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Start the background monitoring thread (skip in debug for easier testing)
    if not os.environ.get('DEBUG'):
        monitor_thread = Thread(target=monitor_updates, daemon=True)
        monitor_thread.start()

    app.run(host='0.0.0.0', port=port, debug=bool(os.environ.get('DEBUG')))