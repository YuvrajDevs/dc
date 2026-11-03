"""Optional LLM fallback for questions the planner does not understand.

The model only *proposes* SQL. It goes through exactly the same validation as everything else,
so a wrong or hostile answer is refused, not run. No key is stored in the repo: set
``ANTHROPIC_API_KEY`` (and optionally ``TALLY_ASK_MODEL``) in the environment.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Protocol


class SQLProvider(Protocol):
    name: str

    def generate(self, question: str, schema_prompt: str) -> str: ...


SYSTEM = (
    "You write a single read-only DuckDB SELECT query that answers the user's question about a "
    "payments reconciliation warehouse. Use only the tables listed, always schema-qualified "
    "(for example recon.findings). Never write anything except one SELECT. Amounts are integer "
    "minor units (divide by 100). Reply with only the SQL in a ```sql fenced block."
)


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("TALLY_ASK_MODEL", "claude-sonnet-5-5")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def generate(self, question: str, schema_prompt: str) -> str:
        body = json.dumps({
            "model": self.model, "max_tokens": 600, "system": SYSTEM,
            "messages": [{"role": "user", "content": f"Tables:\n{schema_prompt}\n\nQuestion: {question}"}],
        })  # fmt: skip
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body.encode(),
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"},
        )  # fmt: skip
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return extract_sql("".join(b.get("text", "") for b in data.get("content", [])))


def default_provider() -> SQLProvider | None:
    p = AnthropicProvider()
    return p if p.available else None
