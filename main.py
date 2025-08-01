from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from config import config
import google.generativeai as genai
import mysql.connector
import requests
import re
import os
import json
from logger import logger

def send_zulip_message(to, msg_type, subject, content):
    data = {
        "type": msg_type,
        "to": to,
        "content": content
    }
    if msg_type == "stream":
        data["subject"] = subject

    requests.post(
        f"{config.ZULIP_SITE}/api/v1/messages",
        data=data,
        auth=(config.ZULIP_BOT_EMAIL, config.ZULIP_BOT_TOKEN)
    )

def submit_query(query):
    conn = mysql.connector.connect(
        host = config.DB_HOST,
        port = 3306,
        database = config.DB_NAME,
        user = config.DB_USER,
        password = config.DB_PASSWORD,
        charset = 'utf8mb4',
        collation = 'utf8mb4_unicode_ci'
    )

    db = conn.cursor()
    db.execute(query)
    rows = db.fetchall()
    result = ""
    for row in rows:
        result += str(row) + ", "

    db.close()
    conn.close()
    return result

FORBIDDEN_SQL_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "REPLACE", "CREATE"
]

def is_safe_sql(query: str) -> bool:
    cleaned_query = re.sub(r"\s+", " ", query).strip().upper()

    for keyword in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", cleaned_query):
            return False

    return True


with open("./data/DDLs.rtf", "r") as f:
    database_context = f.read()

with open("./data/system_prompt_rules.txt") as f:
    system_prompt_rules = f.read()

app = FastAPI(docs_url = "/")

# Enable CORS if you're calling from a browser/frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

intent_prompt = (
    "You are an intent classifier. A user has sent a message."
    "Your task is to classify their intent into one of the following categories:\n"
    "- database: The user wants to query or access information from the database.\n"
    "- chatbot: The user is asking about the chatbot itself, like its purpose, name, capabilities, etc.\n"
    "- other: Anything that does not fit the above categories.\n"
    "Respond ONLY with one of the following words: database, chatbot, other.\n"
)

chatbot_prompt = (
    "You are Fred, an AI-powered assistant integrated with Zulip. The database you are an interface for has a lot"
    "of information relating to unfoldingWord’s work in Bible translation. Fred generates safe, read-only SQL"
    "queries based on the user's natural language request. However, Fred is not an SQL assistant and doesn’t help"
    "the user with questions about SQL. It has access to the database schema and follows strict system rules when"
    "generating SQL. It executes safe queries (only SELECT/read operations) and summarizes the results in natural"
    "language. The user is asking about you directly—a question like what you do, how you work, or what your name is."
    "Answer clearly and briefly, as a helpful assistant would. Don't generate SQL or refer to specific database contents."
)

other_prompt = (
    "You are Fred, an AI-powered assistant integrated with Zulip. The database you are an interface for has a lot"
    "of information relating to unfoldingWord’s work in Bible translation. Fred generates safe, read-only SQL"
    "queries based on the user's natural language request. However, Fred is not an SQL assistant and doesn’t help"
    "the user with questions about SQL. It has access to the database schema and follows strict system rules when"
    "generating SQL. It executes safe queries (only SELECT/read operations) and summarizes the results in natural"
    "language. The user has asked something of you that is an unsupported function of this chatbot. Kindly explain"
    "to the user that you can't help them with that, and redirect them by informing them of things you can do."
)

sql_prompt = (
    "You are an SQL assistant.You will generate SQL queries based on the the user's request and the database information that was given to you."
    "Only return the SQL query — no explanation, no Markdown, no code block formatting."
    "You are a read-only assistant. Under no circumstances should you ever modify the database."
    "If the user asks you to do so, inform them that you are not able to do that. \n"
    f"Here is the database schema: \n{database_context}"
    f"Here are rules you must adhere to when creating sql queries: \n{system_prompt_rules}"

)

answer_prompt = (
    "You are a data summarizer. The user asked a question and you've been given the raw SQL result."
    "Based on that result, write a clear and concise natural-language answer."
    "Make sure to restate the user's question in the answer."
)

# Initialize genai client
genai.configure(api_key=config.GENAI_API_KEY)

intent_model = genai.GenerativeModel(
    model_name="gemini-2.5-pro",
    system_instruction=intent_prompt
)

chatbot_model = genai.GenerativeModel(
    model_name="gemini-2.5-pro",
    system_instruction=chatbot_prompt
)

other_model = genai.GenerativeModel(
    model_name="gemini-2.5-pro",
    system_instruction=other_prompt
)

sql_model = genai.GenerativeModel(
    model_name = "gemini-2.5-pro",
    system_instruction = sql_prompt
)

answer_model = genai.GenerativeModel(
    model_name = "gemini-2.5-pro",
    system_instruction = answer_prompt
)

# Define what the client sends
class ZulipMessage(BaseModel):
    content: str
    sender_email: str
    subject: str
    type: str

class ChatRequest(BaseModel):
    message: ZulipMessage

# Define what the server sends back
class ChatResponse(BaseModel):
    response: str

CHAT_HISTORY_DIR = "./data/chat_histories"
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

def get_user_history_path(email: str) -> str:
    safe_email = email.replace("@", "_at_").replace(".", "_dot_")
    return os.path.join(CHAT_HISTORY_DIR, f"{safe_email}.json")

def load_history(email: str):
    path = get_user_history_path(email)
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except json.JSONDecodeError:
        logger.info("chat history for %s is corrupted. starting fresh.", email)
    return []

def save_history(email: str, history):
    path = get_user_history_path(email)
    with open(path, "w") as f:
        json.dump(history, f, indent=2)


def process_user_message(message):
    try:
        history = load_history(message.sender_email)

        logger.info("%s sent message '%s'", message.sender_email, message.content)

        # Determine intent
        intent_response = intent_model.generate_content(message.content)
        intent = intent_response.text.strip().lower()

        logger.info("Intent classified as: %s", intent)

        response = ""

        if intent == "chatbot":
            chatbot_session = chatbot_model.start_chat(history=history)
            chatbot_reply = chatbot_session.send_message(message.content)

            history.append({"role": "user", "parts": [message.content]})
            history.append({"role": "model", "parts": [chatbot_reply.text]})
            save_history(message.sender_email, history)

            response = chatbot_reply.text

        elif intent == "other":
            other_session = other_model.start_chat(history=history)
            other_reply = other_session.send_message(message.content)

            history.append({"role": "user", "parts": [message.content]})
            history.append({"role": "model", "parts": [other_reply.text]})
            save_history(message.sender_email, history)

            response = other_reply.text


        elif intent == "database":
            # Default case: treat as database query
            sql_chat_session = sql_model.start_chat(history=history)
            sql_message = sql_chat_session.send_message(message.content)

            logger.info("SQL generated: %s", sql_message.text)

            history.append({"role": "user", "parts": [message.content]})
            history.append({"role": "model", "parts": [sql_message.text]})

            if not is_safe_sql(sql_message.text):
                raise ValueError("Unsafe SQL query detected — blocked from execution.")

            database_data = submit_query(sql_message.text)

            answer_chat_session = answer_model.start_chat(history=history)

            answer_request = (
                f"The SQL query returned {database_data}. "
                "Answer the user's question using this data."
            )
            answer_message = answer_chat_session.send_message(answer_request)

            history.append({"role": "model", "parts": [database_data]})
            history.append({"role": "model", "parts": [answer_message.text]})

            save_history(message.sender_email, history)

            response = answer_message.text

        logger.info("Fred response: %s", response)

        send_zulip_message(
            to=[message.sender_email],
            msg_type=message.type,
            subject=message.subject,
            content=response
        )

    except Exception as e:
        logger.info("Error: %s", e)

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    # 1. Send immediate reply
    thinking_reply = "Fred is thinking..."
    background_tasks.add_task(process_user_message, request.message)

    # 2. Send the quick acknowledgment back to Zulip
    send_zulip_message(
        to=[request.message.sender_email],
        msg_type=request.message.type,
        subject=request.message.subject,  # Stream messages need subject
        content=thinking_reply
    )

    return ChatResponse(response="")

