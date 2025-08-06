import requests
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json

# === Google Sheets Setup ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Fred Testing").sheet1  # Your sheet name

# === Chatbot API Setup ===
API_URL = "https://6060df8f8830.ngrok-free.app/chat"  # Your FastAPI endpoint
sender_email = "test@example.com"
subject = "Fred Test"
msg_type = "private"
CHAT_HISTORY_PATH = "./data/chat_histories"

# === Questions to Test ===
questions = [
    "How many languages is unfoldingWord working in?",
    "What are the top 10 countries with the most language engagements?",
    "Which languages have an active Bible translation project right now?",
    "List all the countries where unfoldingWord is currently working.",
    "How many translation projects started this year?",
    "Which language engagements started after 2022?",
    "What countries have more than 3 active language engagements?",
    "Which projects have completed the translation of the book of Luke?",
    "Show me languages in Africa with projects that are currently paused.",
    "How many languages have had translation work for at least 5 years?",
    "Which organizations are supporting translation work in Asia?",
    "For each country, how many languages are being translated?",
    "List language engagements that have both Old and New Testament translation in progress.",
    "What is the average duration of a language engagement project?",
    "Which projects have transitioned from planning to active status this year?",
    "Can you help me write SQL queries?",
    "What’s the weather in South Sudan right now?",
    "Tell me how to build a chatbot like you.",
    "What is your name?",
    "What do you do exactly?",
    "Who built you?",
    "How do you work with Zulip?"
]

# === Helper to load previous history length ===
def load_history(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

# === Run Tests ===
for q in questions:
    print(f"--- Sending: {q}")

    # Load pre-send history
    safe_email = sender_email.replace("@", "_at_").replace(".", "_dot_")
    history_file = os.path.join(CHAT_HISTORY_PATH, f"{safe_email}.json")
    previous_history = load_history(history_file)
    prev_len = len(previous_history)

    # Send request
    message = {
        "message": {
            "content": q,
            "sender_email": sender_email,
            "subject": subject,
            "type": msg_type
        }
    }

    try:
        res = requests.post(API_URL, json=message)
        if res.status_code != 200:
            print(f"❌ Failed to send: {res.status_code} - {res.text}")
            continue

        print("✅ Message sent. Waiting for Fred to respond...")
        time.sleep(35)

        # Load new history and isolate new messages
        new_history = load_history(history_file)
        new_entries = new_history[prev_len:]

        last_sql = ""
        llm_response = ""

        model_messages = [h for h in new_entries if h["role"] == "model"]

        for i, h in enumerate(model_messages):
            text = h["parts"][0]
            if "SELECT" in text.upper() and not last_sql:
                last_sql = text
                # Try to get the message 2 steps ahead if it exists
                if i + 2 < len(model_messages):
                    llm_response = model_messages[i + 2]["parts"][0]
                elif i + 1 < len(model_messages):
                    llm_response = model_messages[i + 1]["parts"][0]
                break  # Done once we find the first SQL + LLM response

        # Log to Google Sheet
        sheet.append_row([q, last_sql, llm_response])
        print("🟢 Logged to sheet.")

    except Exception as e:
        print(f"❌ Error: {e}")
