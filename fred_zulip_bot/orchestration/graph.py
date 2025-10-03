"""LangGraph orchestration helpers for chat processing."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any, Optional, Protocol, TypedDict, cast

from fred_zulip_bot.core.models import ChatRequest, ZulipMessage
from fred_zulip_bot.services.intent_service import IntentType

try:
    LANGGRAPH_GRAPH: ModuleType = import_module("langgraph.graph")
except ModuleNotFoundError as exc:  # pragma: no cover - hard dependency
    raise RuntimeError("langgraph is required to build the chat orchestration graph") from exc

END: Any = LANGGRAPH_GRAPH.END
StateGraph: Any = LANGGRAPH_GRAPH.StateGraph


class ChatGraphService(Protocol):
    """Interface required by the LangGraph orchestration builder."""

    def classify_intent(self, message: ZulipMessage) -> IntentType: ...

    def handle_chatbot(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str: ...

    def handle_other(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str: ...

    def handle_database(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> tuple[str, str, str]: ...


class GraphState(TypedDict, total=False):
    """State container passed through the LangGraph nodes."""

    request: ChatRequest
    history: list[dict[str, Any]]
    intent: Optional[IntentType]  # noqa: UP007
    sql: Optional[str]  # noqa: UP007
    result: Optional[str]  # noqa: UP007
    response: Optional[str]  # noqa: UP007


class GraphRunner(Protocol):
    """Subset of the LangGraph runner interface used by the chat service."""

    def invoke(self, state: GraphState) -> GraphState: ...


def build_chat_graph(*, chat_service: ChatGraphService, logger: Any) -> GraphRunner:
    """Return a compiled LangGraph that mirrors the legacy chat flow."""

    graph = StateGraph(GraphState)

    def classify_intent_node(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        intent = chat_service.classify_intent(request.message)
        logger.info("LangGraph node=classify_intent intent=%s", intent.value)
        return {"intent": intent}

    def route_intent(state: GraphState) -> str:
        intent = state.get("intent")
        if isinstance(intent, IntentType):
            return intent.value
        if isinstance(intent, str):
            cleaned = intent.strip().lower()
            if cleaned in {item.value for item in IntentType}:
                return cleaned
        return IntentType.OTHER.value

    def chatbot_node(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        history = state["history"]
        response = chat_service.handle_chatbot(request.message, history)
        logger.info("LangGraph node=chatbot response_chars=%s", len(response or ""))
        return {"response": response}

    def other_node(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        history = state["history"]
        response = chat_service.handle_other(request.message, history)
        logger.info("LangGraph node=other response_chars=%s", len(response or ""))
        return {"response": response}

    def database_node(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        history = state["history"]
        response, sql_text, result_text = chat_service.handle_database(
            request.message,
            history,
        )
        logger.info("LangGraph node=database has_sql=%s", bool(sql_text))
        return {
            "response": response,
            "sql": sql_text,
            "result": result_text,
        }

    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("chatbot", chatbot_node)
    graph.add_node("other", other_node)
    graph.add_node("database", database_node)

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_intent,
        {
            IntentType.CHATBOT.value: "chatbot",
            IntentType.OTHER.value: "other",
            IntentType.DATABASE.value: "database",
        },
    )
    graph.add_edge("chatbot", END)
    graph.add_edge("other", END)
    graph.add_edge("database", END)

    compiled = graph.compile()
    return cast(GraphRunner, compiled)
