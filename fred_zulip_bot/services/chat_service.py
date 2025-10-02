"""Chat orchestration service."""

from __future__ import annotations

from typing import Any

import google.generativeai as genai
from fastapi import BackgroundTasks, HTTPException

from fred_zulip_bot.adapters.history_repo.base import HistoryRepository
from fred_zulip_bot.adapters.mysql_client import MySqlClient
from fred_zulip_bot.adapters.zulip_client import ZulipClient
from fred_zulip_bot.core.models import ChatRequest, ChatResponse, ZulipMessage
from fred_zulip_bot.services import intent_service
from fred_zulip_bot.services.sql_service import SqlService


class ChatService:
    """Handle chat requests by coordinating adapters and LLM prompts."""

    def __init__(
        self,
        *,
        zulip_client: ZulipClient,
        history_repo: HistoryRepository,
        mysql_client: MySqlClient,
        sql_service: SqlService,
        auth_token: str,
        logger: Any,
        api_key: str,
        primary_model: str = "gemini-2.5-pro",
        fallback_model: str = "gemini-2.5-flash",
    ) -> None:
        self._zulip_client = zulip_client
        self._history_repo = history_repo
        self._mysql_client = mysql_client
        self._sql_service = sql_service
        self._auth_token = auth_token
        self._logger = logger
        self._primary_model = primary_model
        self._fallback_model = fallback_model

        genai.configure(api_key=api_key)  # type: ignore[attr-defined]

    def handle_chat_request(
        self,
        request: ChatRequest,
        background_tasks: BackgroundTasks,
    ) -> ChatResponse:
        """Validate token, enqueue processing, and send acknowledgement."""

        if request.token != self._auth_token:
            raise HTTPException(status_code=401, detail="Unauthorized Request")

        background_tasks.add_task(self.process_user_message, request.message)

        try:
            self._zulip_client.send(
                to=[request.message.sender_email],
                msg_type=request.message.type,
                subject=request.message.subject,
                content="One moment, generating response...",
                channel_name=request.message.display_recipient,
            )
        except Exception:
            self._logger.error("Send Zulip Message Failed", exc_info=True)
            raise HTTPException(status_code=500, detail="Send Zulip Message Failed") from None

        return ChatResponse()

    def process_user_message(self, message: ZulipMessage) -> None:
        """Process a single Zulip message in the background."""

        try:
            history = self._history_repo.get(message.sender_email)

            self._logger.info("%s sent message '%s'", message.sender_email, message.content)

            history.append({"role": "user", "parts": [message.content]})
            self._history_repo.save(message.sender_email, history)

            intent = intent_service.determine_intent(
                lambda prompt, use_history: self._ask_model(message, prompt, use_history)
            )

            self._logger.info("Intent classified as: %s", intent)

            response_text = ""

            if intent == "chatbot":
                chatbot_reply = self._ask_model(
                    message,
                    intent_service.CHATBOT_PROMPT,
                    use_history=True,
                )
                history.append({"role": "model", "parts": [chatbot_reply.text]})
                self._history_repo.save(message.sender_email, history)
                response_text = chatbot_reply.text

            elif intent == "other":
                other_reply = self._ask_model(
                    message,
                    intent_service.OTHER_PROMPT,
                    use_history=True,
                )
                history.append({"role": "model", "parts": [other_reply.text]})
                self._history_repo.save(message.sender_email, history)
                response_text = other_reply.text

            elif intent == "database":
                sql_message = self._ask_model(
                    message,
                    self._sql_service.sql_prompt,
                    use_history=True,
                )

                self._logger.info("SQL generated: %s", sql_message.text)

                history.append({"role": "model", "parts": [sql_message.text]})

                if not self._sql_service.is_safe_sql(sql_message.text):
                    raise ValueError("Unsafe SQL query detected — blocked from execution.")

                database_data = self._mysql_client.select(sql_message.text)

                if database_data != "salvage":
                    history.append({"role": "model", "parts": [database_data]})
                    summary_content = (
                        f"The SQL query returned {database_data}. "
                        "Answer the user's question using this data."
                    )
                else:
                    summary_content = (
                        "A different message instead of SQL was generated. Use this"
                        f"message to answer the user's question. Message: {database_data}"
                    )

                answer_request = ZulipMessage(
                    content=summary_content,
                    display_recipient=message.display_recipient,
                    sender_email=message.sender_email,
                    subject=message.subject,
                    type=message.type,
                )

                answer_message = self._ask_model(
                    answer_request,
                    self._sql_service.answer_prompt,
                    use_history=True,
                )

                history.append({"role": "model", "parts": [answer_message.text]})
                response_text = answer_message.text

                self._history_repo.save(message.sender_email, history)

            if response_text:
                self._logger.info("Fred response: %s", response_text)

                self._zulip_client.send(
                    to=[message.sender_email],
                    msg_type=message.type,
                    subject=message.subject,
                    content=response_text,
                    channel_name=message.display_recipient,
                )
        except Exception as exc:
            self._logger.error("Error: %s", exc)

    def _ask_model(
        self,
        message: ZulipMessage,
        prompt: str,
        use_history: bool,
        *,
        model_override: str | None = None,
        allow_fallback: bool = True,
    ) -> Any:
        model_name = model_override or self._primary_model
        history = self._history_repo.get(message.sender_email) if use_history else None

        try:
            model = genai.GenerativeModel(  # type: ignore[attr-defined]
                model_name=model_name,
                system_instruction=prompt,
            )

            if history:
                chat_session = model.start_chat(history=history)  # type: ignore[arg-type]
                reply = chat_session.send_message(message.content)
            else:
                reply = model.generate_content(message.content)

            if not getattr(reply, "candidates", None):
                raise ValueError("no text returned")

            first_candidate = reply.candidates[0]
            if not getattr(first_candidate, "content", None) or not first_candidate.content.parts:
                raise ValueError("no text returned")

            return reply
        except Exception:
            self._logger.error("gemini model %s failed", model_name, exc_info=True)
            if allow_fallback and model_name == self._primary_model:
                return self._ask_model(
                    message,
                    prompt,
                    use_history,
                    model_override=self._fallback_model,
                    allow_fallback=False,
                )

            raise HTTPException(status_code=500, detail="Gemini model failed") from None
