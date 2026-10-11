"""Ask the agent from the terminal and watch the event stream.

Usage (from backend/):  uv run python -m scripts.ask "Which hazmat shipments used a non-certified carrier?"
"""

import asyncio
import logging
import sys

from app.agent.events import DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent, ToolResultEvent
from app.agent.llm import build_llm
from app.agent.service import OpsAgent, TurnResult
from app.agent.tools.database import OperationalDB
from app.agent.tools.documents import DocumentIndex
from app.config import get_settings
from app.data.seed import ensure_fresh
from app.domain.facts import get_facts

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


async def main(question: str) -> None:
    settings, facts = get_settings(), get_facts()
    ensure_fresh(settings.db_path, facts)
    agent = OpsAgent(
        settings,
        facts,
        build_llm(settings),
        DocumentIndex.load_or_build(settings),
        OperationalDB(settings.db_path, settings.sql_row_limit),
    )
    print(f"{BOLD}Q: {question}{RESET}\n")
    async for ev in agent.stream([], question, TurnResult()):
        match ev:
            case ToolCallEvent():
                print(f"{DIM}→ {ev.tool}({ev.args}){RESET}")
            case ToolResultEvent():
                status = "ok" if ev.ok else "ERROR"
                detail = getattr(ev.data, "error", None) or ""
                print(f"{DIM}← {ev.tool} {status} {ev.duration_ms} ms {detail}{RESET}")
            case TokenEvent():
                print(ev.delta, end="", flush=True)
            case DoneEvent():
                u = ev.usage
                print(f"\n\n{DIM}[{len(ev.citations)} citations | {u.llm_calls} LLM calls | "
                      f"{u.prompt_tokens}+{u.completion_tokens} tokens | {ev.latency_ms} ms]{RESET}")  # fmt: skip
                for c in ev.citations:
                    print(f"{DIM}  [{c.n}] {c.doc_id} p.{c.page}{RESET}")
            case ErrorEvent():
                print(f"\nERROR {ev.code}: {ev.message}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(" ".join(sys.argv[1:]) or "Can I book a dock at CHI1 tomorrow morning?"))
