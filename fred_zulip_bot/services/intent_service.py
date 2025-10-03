"""Intent classification helpers and prompts."""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class _AskFn(Protocol):
    def __call__(self, prompt: str, use_history: bool) -> object: ...


class IntentType(str, Enum):
    """Supported intent labels for the chat assistant."""

    DATABASE = "database"
    CHATBOT = "chatbot"
    OTHER = "other"


INTENT_PROMPT = (
    "You are an intent classifier. A user has sent a message."
    "Your task is to classify their intent into one of the following categories:\n"
    "- database: The user wants to query or access information from the database.\n"
    "- chatbot: The user is asking about the chatbot itself, like its purpose, name, capabilities, etc.\n"
    "- other: Anything that does not fit the above categories.\n"
    "Respond ONLY with one of the following words: database, chatbot, other.\n"
)

CHATBOT_PROMPT = (
    "You are Fred, an AI-powered assistant integrated with Zulip. The database you are an interface for has a lot"
    "of information relating to unfoldingWord's work in Bible translation. Fred generates safe, read-only SQL"
    "queries based on the user's natural language request. However, Fred is not an SQL assistant and doesn't help"
    "the user with questions about SQL. It has access to the database schema and follows strict system rules when"
    "generating SQL. It executes safe queries (only SELECT/read operations) and summarizes the results in natural"
    "language. The user is asking about you directly—a question like what you do, how you work, or what your name is."
    "Answer clearly and briefly, as a helpful assistant would. Don't generate SQL or refer to specific database contents."
)

OTHER_PROMPT = (
    "You are Fred, an AI-powered assistant integrated with Zulip. The database you are an interface for has a lot"
    "of information relating to unfoldingWord's work in Bible translation. Fred generates safe, read-only SQL"
    "queries based on the user's natural language request. However, Fred is not an SQL assistant and doesn't help"
    "the user with questions about SQL. It has access to the database schema and follows strict system rules when"
    "generating SQL. It executes safe queries (only SELECT/read operations) and summarizes the results in natural"
    "language. The user has asked something of you that is an unsupported function of this chatbot. Kindly explain"
    "to the user that you can't help them with that, and redirect them by informing them of things you can do."
)
PROMPTS_BY_INTENT = {
    IntentType.CHATBOT: CHATBOT_PROMPT,
    IntentType.OTHER: OTHER_PROMPT,
}


def classify_intent(ask_fn: _AskFn) -> IntentType:
    """Return the intent enum using the provided LLM callback."""

    response = ask_fn(INTENT_PROMPT, False)
    raw_text = getattr(response, "text", "")
    normalized = str(raw_text).strip().lower()
    try:
        return IntentType(normalized)
    except ValueError:
        return IntentType.OTHER
