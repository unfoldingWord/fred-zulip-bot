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

    def converse_with_fred_bot(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str: ...

    def handle_unsupported_function(
        self,
        message: ZulipMessage,
        history: list[dict[str, Any]],
    ) -> str: ...

    def query_fred(
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

    def classify_intent(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        intent = chat_service.classify_intent(request.message)
        logger.info("LangGraph node=classify_intent_node intent=%s", intent.value)
        return {"intent": intent}

    def route_intent(state: GraphState) -> str:
        intent = state.get("intent")
        if isinstance(intent, IntentType):
            return intent.value
        if isinstance(intent, str):
            cleaned = intent.strip().lower()
            if cleaned in {item.value for item in IntentType}:
                return cleaned
        return IntentType.HANDLE_UNSUPPORTED_FUNCTION.value

    def converse_with_fred_bot(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        history = state["history"]
        response = chat_service.converse_with_fred_bot(request.message, history)
        logger.info(
            "LangGraph node=converse_with_fred_bot response_chars=%s",
            len(response or ""),
        )
        return {"response": response}

    def handle_unsupported_function(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        history = state["history"]
        response = chat_service.handle_unsupported_function(request.message, history)
        logger.info(
            "LangGraph node=handle_unsupported_function response_chars=%s",
            len(response or ""),
        )
        return {"response": response}

    def query_fred(state: GraphState) -> dict[str, Any]:
        request = state["request"]
        history = state["history"]
        response, sql_text, result_text = chat_service.query_fred(
            request.message,
            history,
        )
        logger.info("LangGraph node=query_fred has_sql=%s", bool(sql_text))
        return {
            "response": response,
            "sql": sql_text,
            "result": result_text,
        }

    graph.add_node("classify_intent_node", classify_intent)
    graph.add_node("converse_with_fred_bot_node", converse_with_fred_bot)
    graph.add_node("handle_unsupported_function_node", handle_unsupported_function)
    graph.add_node("query_fred_node", query_fred)

    graph.set_entry_point("classify_intent_node")
    graph.add_conditional_edges(
        "classify_intent_node",
        route_intent,
        {
            IntentType.CONVERSE_WITH_FRED_BOT.value: "converse_with_fred_bot_node",
            IntentType.HANDLE_UNSUPPORTED_FUNCTION.value: "handle_unsupported_function_node",
            IntentType.QUERY_FRED.value: "query_fred_node",
        },
    )
    graph.add_edge("converse_with_fred_bot_node", END)
    graph.add_edge("handle_unsupported_function_node", END)
    graph.add_edge("query_fred_node", END)

    compiled = graph.compile()
    return cast(GraphRunner, compiled)
