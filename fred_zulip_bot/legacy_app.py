"""Legacy chat handling logic retained during the refactor."""

from __future__ import annotations

import json
import os
import re
from typing import Any, cast

import google.generativeai as genai
import mysql.connector
import requests
from fastapi import BackgroundTasks, HTTPException

from config import config
from fred_zulip_bot.core.models import ChatRequest, ChatResponse, ZulipMessage
from logger import logger

if config.TEST_MODE:
    zulip_bot_email = config.ZULIP_BOT_EMAIL_TEST
    zulip_bot_token = config.ZULIP_BOT_TOKEN_TEST
    zulip_auth_token = config.ZULIP_AUTH_TOKEN_TEST
else:
    zulip_bot_email = config.ZULIP_BOT_EMAIL
    zulip_bot_token = config.ZULIP_BOT_TOKEN
    zulip_auth_token = config.ZULIP_AUTH_TOKEN


def send_zulip_message(
    to: list[str],
    msg_type: str,
    subject: str,
    content: str,
    channel_name: Any,
) -> None:
    """Send a message back to Zulip using the configured bot credentials."""

    data: dict[str, Any] = {
        "type": msg_type,
        "to": to,
        "content": content,
    }
    if msg_type == "stream":
        data["subject"] = subject
        data["to"] = channel_name

    requests.post(  # noqa: S113 - legacy logic without explicit timeout
        f"{config.ZULIP_SITE}/api/v1/messages",
        data=data,
        auth=(zulip_bot_email, zulip_bot_token),
    )


def submit_query(query: str) -> str:
    """Execute a read-only SQL query and return the serialized rows."""

    try:
        conn = mysql.connector.connect(
            host=config.DB_HOST,
            port=3306,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
        )

        db = conn.cursor()
        db.execute(query)
        rows = db.fetchall()
        result = ""
        for row in rows:
            result += f"{row}, "

        db.close()
        conn.close()
        return result
    except Exception:
        logger.error("invalid sql generated", exc_info=True)
        return "salvage"


FORBIDDEN_SQL_KEYWORDS = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "TRUNCATE",
    "ALTER",
    "REPLACE",
    "CREATE",
]


def is_safe_sql(query: str) -> bool:
    """Determine whether the SQL query is safe to execute."""

    cleaned_query = re.sub(r"\s+", " ", query).strip().upper()

    for keyword in FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{keyword}\b", cleaned_query):
            return False

    return True


with open("context/DDLs.rtf") as ddl_file:
    database_context = ddl_file.read()

with open("context/system_prompt_rules.txt") as prompt_file:
    system_prompt_rules = prompt_file.read()

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
    "of information relating to unfoldingWord's work in Bible translation. Fred generates safe, read-only SQL"
    "queries based on the user's natural language request. However, Fred is not an SQL assistant and doesn't help"
    "the user with questions about SQL. It has access to the database schema and follows strict system rules when"
    "generating SQL. It executes safe queries (only SELECT/read operations) and summarizes the results in natural"
    "language. The user is asking about you directly—a question like what you do, how you work, or what your name is."
    "Answer clearly and briefly, as a helpful assistant would. Don't generate SQL or refer to specific database contents."
)

other_prompt = (
    "You are Fred, an AI-powered assistant integrated with Zulip. The database you are an interface for has a lot"
    "of information relating to unfoldingWord's work in Bible translation. Fred generates safe, read-only SQL"
    "queries based on the user's natural language request. However, Fred is not an SQL assistant and doesn't help"
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
    "Make sure to restate the user's question in the answer. If asked about Population, cite the"
    "datasource either as Joshua Project or Progress Bible based on the SQL table used."
)

genai.configure(api_key=config.GENAI_API_KEY)  # type: ignore[attr-defined]

current_model = "gemini-2.5-pro"


CHAT_HISTORY_DIR = "./data/chat_histories"
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)

MAX_HISTORY_LENGTH = 20


def get_user_history_path(email: str) -> str:
    safe_email = email.replace("@", "_at_").replace(".", "_dot_")
    return os.path.join(CHAT_HISTORY_DIR, f"{safe_email}.json")


def load_history(email: str) -> list[dict[str, Any]]:
    path = get_user_history_path(email)
    try:
        if os.path.exists(path):
            with open(path) as history_file:
                return cast(list[dict[str, Any]], json.load(history_file))
    except json.JSONDecodeError:
        logger.info("chat history for %s is corrupted. starting fresh.", email)
    return []


def save_history(email: str, history: list[dict[str, Any]]) -> None:
    trimmed_history = history[-MAX_HISTORY_LENGTH:]
    path = get_user_history_path(email)
    with open(path, "w") as history_file:
        json.dump(trimmed_history, history_file, indent=2)


def ask_gemini(
    message: ZulipMessage,
    model_name: str,
    prompt: str,
    use_history: bool,
) -> Any:
    text_error = False
    try:
        model = genai.GenerativeModel(  # type: ignore[attr-defined]
            model_name=model_name,
            system_instruction=prompt,
        )

        if use_history:
            history = load_history(message.sender_email)
            chat_session = model.start_chat(history=history)  # type: ignore[arg-type]
            reply = chat_session.send_message(message.content)
        else:
            reply = model.generate_content(message.content)

        if reply.candidates and reply.candidates[0].content.parts:
            return reply
        text_error = True
        raise Exception("no text returned")

    except Exception:
        logger.error("gemini model %s failed", model_name, exc_info=True)
        if text_error:
            return ask_gemini(message, "gemini-2.5-pro", prompt, use_history)
        if model_name == "gemini-2.5-pro":
            return ask_gemini(message, "gemini-2.5-flash", prompt, use_history)
        raise HTTPException(status_code=500, detail="Gemini model failed") from None


def process_user_message(message: ZulipMessage) -> None:
    try:
        history = load_history(message.sender_email)

        logger.info("%s sent message '%s'", message.sender_email, message.content)

        history.append({"role": "user", "parts": [message.content]})
        save_history(message.sender_email, history)

        intent_response = ask_gemini(message, current_model, intent_prompt, use_history=False)
        intent = intent_response.text.strip().lower()

        logger.info("Intent classified as: %s", intent)

        response = ""

        if intent == "chatbot":
            chatbot_reply = ask_gemini(message, current_model, chatbot_prompt, use_history=True)
            history.append({"role": "model", "parts": [chatbot_reply.text]})
            save_history(message.sender_email, history)

            response = chatbot_reply.text

        elif intent == "other":
            other_reply = ask_gemini(message, current_model, other_prompt, use_history=True)
            history.append({"role": "model", "parts": [other_reply.text]})
            save_history(message.sender_email, history)

            response = other_reply.text

        elif intent == "database":
            sql_message = ask_gemini(message, current_model, sql_prompt, use_history=True)

            logger.info("SQL generated: %s", sql_message.text)

            history.append({"role": "model", "parts": [sql_message.text]})

            if not is_safe_sql(sql_message.text):
                raise ValueError("Unsafe SQL query detected — blocked from execution.")

            database_data = submit_query(sql_message.text)

            if database_data != "salvage":
                history.append({"role": "model", "parts": [database_data]})

                answer_content = (
                    f"The SQL query returned {database_data}. "
                    "Answer the user's question using this data."
                )
            else:
                answer_content = (
                    "A different message instead of SQL was generated. Use this"
                    f"message to answer the user's question. Message: {database_data}"
                )

            answer_request = ZulipMessage(
                content=answer_content,
                display_recipient=message.display_recipient,
                sender_email=message.sender_email,
                subject=message.subject,
                type=message.type,
            )

            answer_message = ask_gemini(
                answer_request,
                current_model,
                answer_prompt,
                use_history=True,
            )

            history.append({"role": "model", "parts": [answer_message.text]})

            save_history(message.sender_email, history)

            response = answer_message.text

        logger.info("Fred response: %s", response)

        send_zulip_message(
            to=[message.sender_email],
            msg_type=message.type,
            subject=message.subject,
            content=response,
            channel_name=message.display_recipient,
        )

    except Exception as exc:
        logger.error("Error: %s", exc)


def handle_chat_request(request: ChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    """Validate the request, enqueue work, and send immediate acknowledgment."""

    if request.token != zulip_auth_token:
        raise HTTPException(status_code=401, detail="Unauthorized Request")

    thinking_reply = "One moment, generating response..."
    background_tasks.add_task(process_user_message, request.message)

    try:
        send_zulip_message(
            to=[request.message.sender_email],
            msg_type=request.message.type,
            subject=request.message.subject,
            content=thinking_reply,
            channel_name=request.message.display_recipient,
        )
    except Exception:
        logger.error("Send Zulip Message Failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Send Zulip Message Failed") from None

    return ChatResponse()
