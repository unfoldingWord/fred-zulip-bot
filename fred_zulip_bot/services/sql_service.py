"""SQL guardrails and prompts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

SQL_ALLOW_PREFIX = "SELECT"
DENY_PATTERN = re.compile(
    r"\b(drop|alter|insert|update|delete|truncate|call|create|grant|revoke)\b",
    re.IGNORECASE,
)
DANGEROUS_PATTERN = re.compile(r";|--|/\*|\*/|into\s+outfile|load\s+data", re.IGNORECASE)


class SqlService:
    """Guard SQL execution and expose prompts for generation/summarization."""

    def __init__(
        self,
        ddl_path: Path = Path("context/DDLs.rtf"),
        rules_path: Path = Path("context/system_prompt_rules.txt"),
    ) -> None:
        database_context = ddl_path.read_text()
        system_rules = rules_path.read_text()

        self.sql_prompt = (
            "You are an SQL assistant.You will generate SQL queries based on the the user's request and the database information that was given to you."
            "Only return the SQL query as JSON — no explanation, no Markdown, no code block formatting."
            "The JSON object must contain a single field named sql whose value is the generated SELECT statement."
            "You are a read-only assistant. Under no circumstances should you ever modify the database."
            "If the user asks you to do so, inform them that you are not able to do that. \n"
            f"Here is the database schema: \n{database_context}"
            f"Here are rules you must adhere to when creating sql queries: \n{system_rules}"
        )

        self.sql_rewrite_prompt = (
            "You rewrite follow-up database questions into a single, self-contained request for SQL generation."
            "You will receive the conversation history (oldest first) and the latest user message."
            "Return a JSON object with a rewritten_request field that restates the user's latest ask."
            "Preserve every filter, time period, entity, or constraint implied by the conversation."
            "Do not invent new requirements."
        )

        self.sql_generation_schema: Final[dict[str, Any]] = {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        }
        self.sql_rewrite_schema: Final[dict[str, Any]] = {
            "type": "object",
            "properties": {"rewritten_request": {"type": "string"}},
            "required": ["rewritten_request"],
        }

        self.answer_prompt = (
            "You are a data summarizer. The user asked a question and you've been given the raw SQL result."
            "Based on that result, write a clear and concise natural-language answer."
            "Make sure to restate the user's question in the answer. If asked about Population, cite the"
            "datasource either as Joshua Project or Progress Bible based on the SQL table used."
        )

    @staticmethod
    def is_safe_sql(sql: str) -> bool:
        stripped = sql.strip()
        if not stripped.lower().startswith(SQL_ALLOW_PREFIX.lower()):
            return False

        if DENY_PATTERN.search(stripped):
            return False

        if DANGEROUS_PATTERN.search(stripped):
            return False

        return stripped.count(";") == 0
