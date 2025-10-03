"""Chat orchestration service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import google.generativeai as genai
from fastapi import BackgroundTasks, HTTPException

from fred_zulip_bot.adapters.history_repo.base import HistoryRepository
from fred_zulip_bot.adapters.mysql_client import MySqlClient
from fred_zulip_bot.adapters.zulip_client import ZulipClient
from fred_zulip_bot.core.models import ChatRequest, ChatResponse, ZulipMessage
from fred_zulip_bot.orchestration.graph import GraphState, build_chat_graph
from fred_zulip_bot.services import intent_service
from fred_zulip_bot.services.intent_service import IntentType
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
        enable_langgraph: bool = False,
        primary_model: str = "gemini-2.5-pro",
        fallback_model: str = "gemini-2.5-flash",
    ) -> None:
        self._zulip_client = zulip_client
        self._history_repo = history_repo
        self._mysql_client = mysql_client
        self._sql_service = sql_service
        self._auth_token = auth_token
        self._logger = logger
        self._enable_langgraph = enable_langgraph
        self._primary_model = primary_model
        self._fallback_model = fallback_model
        self._graph_runner: Any | None = None

        self._configure_genai(api_key)

    def handle_chat_request(
        self,
        request: ChatRequest,
        background_tasks: BackgroundTasks,
    ) -> ChatResponse:
        """Validate token, enqueue processing, and send acknowledgement."""

        if request.token != self._auth_token:
            raise HTTPException(status_code=401, detail="Unauthorized Request")

        background_tasks.add_task(self.process_user_message, request)

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

    def process_user_message(self, request: ChatRequest) -> None:
        """Process a single Zulip message in the background."""

        message = request.message

        try:
            history = self._history_repo.get(message.sender_email)

            self._logger.info("%s sent message '%s'", message.sender_email, message.content)

            self._record_user_message(message, history)

            if self._enable_langgraph:
                response_text = self._run_langgraph_flow(request, history)
            else:
                response_text = self._run_legacy_flow(message, history)

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

    def _record_user_message(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> None:
        history.append({"role": "user", "parts": [message.content]})
        self._history_repo.save(message.sender_email, history)

    def _run_legacy_flow(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str:
        intent = self.classify_intent(message)
        self._logger.info("Intent classified as: %s", intent.value)

        if intent is IntentType.CHATBOT:
            return self.handle_chatbot(message, history)

        if intent is IntentType.OTHER:
            return self.handle_other(message, history)

        if intent is IntentType.DATABASE:
            response_text, _, _ = self.handle_database(message, history)
            return response_text

        return ""

    def _run_langgraph_flow(
        self,
        request: ChatRequest,
        history: list[dict[str, Any]],
    ) -> str:
        if self._graph_runner is None:
            self._graph_runner = build_chat_graph(chat_service=self, logger=self._logger)
            self._logger.info("LangGraph orchestrator compiled")

        initial_state: GraphState = {
            "request": request,
            "history": history,
            "intent": None,
            "sql": None,
            "result": None,
            "response": None,
        }

        state: GraphState = self._graph_runner.invoke(initial_state)

        response = state.get("response")
        if response is None:
            return ""

        return response

    def classify_intent(self, message: ZulipMessage) -> IntentType:
        """Determine the user intent using the intent service."""

        return intent_service.classify_intent(
            lambda prompt, use_history: self._ask_model(
                message,
                prompt,
                use_history,
            )
        )

    def handle_chatbot(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str:
        """Generate a chatbot-style response."""

        chatbot_text = self._ask_model_text(
            message,
            intent_service.CHATBOT_PROMPT,
        )
        history.append({"role": "model", "parts": [chatbot_text]})
        self._history_repo.save(message.sender_email, history)
        return chatbot_text

    def handle_other(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str:
        """Generate a response for unsupported requests."""

        other_text = self._ask_model_text(
            message,
            intent_service.OTHER_PROMPT,
        )
        history.append({"role": "model", "parts": [other_text]})
        self._history_repo.save(message.sender_email, history)
        return other_text

    def handle_database(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> tuple[str, str, str]:
        """Generate SQL, execute it, and summarize the result."""

        sql_text = self._ask_model_text(
            message,
            self._sql_service.sql_prompt,
        )

        self._logger.info("SQL generated: %s", sql_text)

        is_safe_sql = self._sql_service.is_safe_sql(sql_text)
        if is_safe_sql:
            database_data = self._mysql_client.select(sql_text)
        else:
            self._logger.info("Unsafe SQL blocked; using fallback response")
            database_data = sql_text

        if is_safe_sql and database_data != "salvage":
            self._logger.info("SQL result captured rows=%s", database_data[:200])
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

        answer_text = self._ask_model_text(
            answer_request,
            self._sql_service.answer_prompt,
        )

        history.append({"role": "model", "parts": [answer_text]})
        self._history_repo.save(message.sender_email, history)

        return answer_text, sql_text, database_data

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
            model = self._create_model(model_name=model_name, prompt=prompt)

            if history:
                chat_session: Any = model.start_chat(history=history)
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

    def _ask_model_text(
        self,
        message: ZulipMessage,
        prompt: str,
        *,
        use_history: bool = True,
    ) -> str:
        response = self._ask_model(message, prompt, use_history)
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        raise ValueError("no text returned")

    def _configure_genai(self, api_key: str) -> None:
        configure = getattr(genai, "configure", None)
        if not callable(configure):  # pragma: no cover - defensive guard
            raise RuntimeError("google.generativeai.configure is unavailable")

        configure(api_key=api_key)

    def _create_model(self, *, model_name: str, prompt: str) -> Any:
        factory_candidate = getattr(genai, "GenerativeModel", None)
        if not callable(factory_candidate):  # pragma: no cover - defensive guard
            raise RuntimeError("google.generativeai.GenerativeModel is unavailable")

        factory: Callable[..., Any] = factory_candidate
        return factory(model_name=model_name, system_instruction=prompt)
