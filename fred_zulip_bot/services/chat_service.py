"""Chat orchestration service."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any, cast

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

DEFAULT_FALLBACK_MESSAGE = (
    "I'm having trouble responding right now. Please report this to my creators."
)

_SQL_PREPROCESS_LOG_SNIPPET_LENGTH = 240

_PROGRESS_CLASSIFY = "Figuring out the best way to help."
_PROGRESS_QUERY = (
    "Checking the database for the details you asked about. This could take some time."
    " Thanks for your patience."
)
_PROGRESS_SUMMARY = "I have the data - summarizing it for you now..."
_PROGRESS_CHATBOT = "Drafting a reply about how I work."
_PROGRESS_UNSUPPORTED = "Working on a helpful explanation since I can't do that directly."
_PROGRESS_UNSAFE = "That request looked unsafe, so I'm sending a fallback instead."


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
        history_max_length: int = 5,
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
        self._history_limit = max(history_max_length, 0)

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
                content="thinking...",
                channel_name=request.message.display_recipient,
            )
        except Exception:
            self._logger.error("Send Zulip Message Failed", exc_info=True)
            raise HTTPException(status_code=500, detail="Send Zulip Message Failed") from None

        return ChatResponse()

    def process_user_message(self, request: ChatRequest) -> None:
        """Process a single Zulip message in the background."""

        message = request.message
        response_text: str | None = None
        history: list[dict[str, Any]] = []
        should_record_response = False

        try:
            history = self._history_repo.get(message.sender_email)
        except Exception:
            self._logger.error(
                "History fetch failed; continuing with empty history",
                exc_info=True,
            )
            history = []

        try:
            self._logger.info("%s sent message '%s'", message.sender_email, message.content)

            self._record_user_message(message, history)

            if self._enable_langgraph:
                response_text = self._run_langgraph_flow(request, history)
            else:
                response_text = self._run_legacy_flow(message, history)

            if not response_text:
                raise ValueError("empty response generated")

            self._logger.info("Fred response: %s", response_text)
        except Exception:
            self._logger.error("Processing user message failed", exc_info=True)
            response_text = DEFAULT_FALLBACK_MESSAGE
            should_record_response = True
        finally:
            if response_text is None:
                response_text = DEFAULT_FALLBACK_MESSAGE
                should_record_response = True

            self._deliver_response(
                message,
                response_text,
                history,
                record_history=should_record_response,
            )

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

        if intent is IntentType.CONVERSE_WITH_FRED_BOT:
            return self.converse_with_fred_bot(message, history)

        if intent is IntentType.HANDLE_UNSUPPORTED_FUNCTION:
            return self.handle_unsupported_function(message, history)

        if intent is IntentType.QUERY_FRED:
            response_text, _, _ = self.query_fred(message, history)
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

        intent = intent_service.classify_intent(
            lambda prompt, use_history: self._ask_model(
                message,
                prompt,
                use_history,
            )
        )
        self._send_progress_update(message, _PROGRESS_CLASSIFY)
        return intent

    def converse_with_fred_bot(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str:
        """Generate a chatbot-style response."""

        self._send_progress_update(message, _PROGRESS_CHATBOT)
        chatbot_text = self._ask_model_text(
            message,
            intent_service.CHATBOT_PROMPT,
        )
        history.append({"role": "model", "parts": [chatbot_text]})
        self._history_repo.save(message.sender_email, history)
        return chatbot_text

    def handle_unsupported_function(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str:
        """Generate a response for unsupported requests."""

        self._send_progress_update(message, _PROGRESS_UNSUPPORTED)
        other_text = self._ask_model_text(
            message,
            intent_service.OTHER_PROMPT,
        )
        history.append({"role": "model", "parts": [other_text]})
        self._history_repo.save(message.sender_email, history)
        return other_text

    def query_fred(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> tuple[str, str, str]:
        """Generate SQL, execute it, and summarize the result."""

        self._send_progress_update(message, _PROGRESS_QUERY)
        rewritten_message_text = self._preprocess_for_sql_transform(message, history)
        sql_request_message = message.model_copy(update={"content": rewritten_message_text})
        sql_payload = self._ask_model_json(
            sql_request_message,
            self._sql_service.sql_prompt,
            use_history=False,
            schema=self._sql_service.sql_generation_schema,
        )

        sql_text = str(sql_payload.get("sql", "")).strip()
        if not sql_text:
            raise ValueError("no sql returned")

        self._logger.info("SQL generated: %s", sql_text)

        is_safe_sql = self._sql_service.is_safe_sql(sql_text)
        if not is_safe_sql:
            self._logger.info("Unsafe SQL blocked; sending friendly fallback")
            self._send_progress_update(message, _PROGRESS_UNSAFE)
            friendly_message = DEFAULT_FALLBACK_MESSAGE
            history.append({"role": "model", "parts": [friendly_message]})
            self._history_repo.save(message.sender_email, history)
            return friendly_message, sql_text, "salvage"

        database_data = self._mysql_client.select(sql_text)
        self._send_progress_update(message, _PROGRESS_SUMMARY)

        if database_data != "salvage":
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

    def _send_progress_update(self, message: ZulipMessage, content: str) -> None:
        try:
            self._zulip_client.send(
                to=[message.sender_email],
                msg_type=message.type,
                subject=message.subject,
                content=content,
                channel_name=message.display_recipient,
            )
        except Exception:
            self._logger.error("Progress update failed", exc_info=True)

    def _preprocess_for_sql_transform(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str:
        relevant_history = self._extract_relevant_history_entries(history)
        without_latest = list(relevant_history)
        if without_latest and without_latest[-1].get("role") == "user":
            latest_parts = without_latest[-1].get("parts", [])
            if len(latest_parts) == 1 and latest_parts[0] == message.content:
                without_latest = without_latest[:-1]

        history_text = self._history_to_text(without_latest)
        history_snippet = self._truncate_for_log(history_text)

        self._logger.info(
            "SQL preprocess before: history_turns=%s latest_message=%r history_snippet=%r",
            len(without_latest),
            self._truncate_for_log(message.content),
            history_snippet,
        )

        if not history_text:
            self._logger.info(
                "SQL preprocess after: rewrite_applied=False reason=no_relevant_history",
            )
            return message.content

        rewrite_input = (
            "Conversation history (oldest to newest):\n"
            f"{history_text}\n\n"
            "Latest user message:\n"
            f"{message.content}"
        )
        rewrite_message = message.model_copy(update={"content": rewrite_input})

        try:
            rewrite_payload = self._ask_model_json(
                rewrite_message,
                self._sql_service.sql_rewrite_prompt,
                use_history=False,
                schema=self._sql_service.sql_rewrite_schema,
            )
        except Exception:
            self._logger.error(
                "SQL preprocess after: rewrite_applied=False reason=rewrite_failed",
                exc_info=True,
            )
            return message.content

        rewritten_request = str(rewrite_payload.get("rewritten_request", "")).strip()
        if not rewritten_request:
            self._logger.info(
                "SQL preprocess after: rewrite_applied=False reason=empty_rewrite",
            )
            return message.content

        rewritten_snippet = self._truncate_for_log(rewritten_request)
        rewrite_applied = rewritten_request != message.content

        self._logger.info(
            "SQL preprocess after: rewrite_applied=%s rewritten_message=%r",
            rewrite_applied,
            rewritten_snippet,
        )

        return rewritten_request

    def _deliver_response(
        self,
        message: ZulipMessage,
        content: str,
        history: list[dict[str, Any]],
        *,
        record_history: bool,
        max_attempts: int = 2,
    ) -> None:
        if record_history:
            history.append({"role": "model", "parts": [content]})
            try:
                self._history_repo.save(message.sender_email, history)
            except Exception:
                self._logger.error("History save failed", exc_info=True)

        for attempt in range(1, max_attempts + 1):
            try:
                self._zulip_client.send(
                    to=[message.sender_email],
                    msg_type=message.type,
                    subject=message.subject,
                    content=content,
                    channel_name=message.display_recipient,
                )
                return
            except Exception:
                self._logger.error(
                    "Send Zulip Message Failed (attempt %s/%s)",
                    attempt,
                    max_attempts,
                    exc_info=True,
                )
        # If all attempts fail we have nothing left to try; log once more for visibility.
        self._logger.error("Exhausted attempts to deliver message to %s", message.sender_email)

    def _ask_model(
        self,
        message: ZulipMessage,
        prompt: str,
        use_history: bool,
        *,
        model_override: str | None = None,
        allow_fallback: bool = True,
        generation_config: dict[str, Any] | None = None,
    ) -> Any:
        model_name = model_override or self._primary_model
        history = self._history_repo.get(message.sender_email) if use_history else None

        try:
            model = self._create_model(
                model_name=model_name,
                prompt=prompt,
                generation_config=generation_config,
            )

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
                    generation_config=generation_config,
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

    def _ask_model_json(
        self,
        message: ZulipMessage,
        prompt: str,
        *,
        schema: dict[str, Any],
        use_history: bool = True,
    ) -> dict[str, Any]:
        generation_config = {
            "response_mime_type": "application/json",
            "response_schema": schema,
        }
        response = self._ask_model(
            message,
            prompt,
            use_history,
            generation_config=generation_config,
        )
        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise ValueError("no json text returned")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            raise ValueError("invalid json returned") from exc
        if not isinstance(parsed, dict):
            raise ValueError("invalid json returned")
        return cast(dict[str, Any], parsed)

    def _extract_relevant_history_entries(
        self,
        history: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        relevant: list[dict[str, Any]] = []
        for entry in history:
            role = entry.get("role")
            parts = entry.get("parts")
            if role not in {"user", "model"}:
                continue
            if not parts:
                continue
            relevant.append({"role": role, "parts": list(parts)})
        if not self._history_limit:
            return relevant
        return relevant[-self._history_limit :]

    @staticmethod
    def _history_to_text(history: Iterable[dict[str, Any]]) -> str:
        lines: list[str] = []
        for entry in history:
            role = entry.get("role", "unknown")
            label = "assistant" if role == "model" else role
            parts = entry.get("parts", [])
            if not parts:
                continue
            text_parts = [str(part) for part in parts if part]
            if not text_parts:
                continue
            lines.append(f"{label}: {' '.join(text_parts)}")
        return "\n".join(lines)

    @staticmethod
    def _truncate_for_log(value: str, limit: int = _SQL_PREPROCESS_LOG_SNIPPET_LENGTH) -> str:
        stripped = value.strip()
        if len(stripped) <= limit:
            return stripped
        return f"{stripped[:limit]}…"

    def _configure_genai(self, api_key: str) -> None:
        configure = getattr(genai, "configure", None)
        if not callable(configure):  # pragma: no cover - defensive guard
            raise RuntimeError("google.generativeai.configure is unavailable")

        configure(api_key=api_key)

    def _create_model(
        self,
        *,
        model_name: str,
        prompt: str,
        generation_config: dict[str, Any] | None = None,
    ) -> Any:
        factory_candidate = getattr(genai, "GenerativeModel", None)
        if not callable(factory_candidate):  # pragma: no cover - defensive guard
            raise RuntimeError("google.generativeai.GenerativeModel is unavailable")

        factory: Callable[..., Any] = factory_candidate
        return factory(
            model_name=model_name,
            system_instruction=prompt,
            generation_config=generation_config,
        )
