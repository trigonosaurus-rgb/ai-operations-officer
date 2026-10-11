"""Agent eval: runs the golden cases (evals/cases.yaml) against the real model.

Usage (from backend/, needs OPENAI_API_KEY; a full run costs a few cents):
    uv run python -m evals.run
    uv run python -m evals.run --only late-arrival,hazmat-audit
    uv run python -m evals.run --category pricing --no-judge
    uv run python -m evals.run --judge-model gpt-5.4-mini --fail-under 90

Each case is scored three ways, from cheap and strict to expensive and flexible:
    routing  every expected tool was called              did it choose the right tools?
    facts    required strings + live DB values present    deterministic, no LLM needed
    judge    LLM-as-judge score 1-5 against a reference    catches what string checks can't
A case passes when all three pass. Results: evals/results/agent.md (+ raw JSON in var/evals/).
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml
from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.prompts import PromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from app.agent.events import DoneEvent, ErrorEvent, ToolCallEvent, ToolResultEvent
from app.agent.llm import build_llm
from app.agent.service import OpsAgent, TurnResult
from app.agent.tools.database import OperationalDB
from app.agent.tools.documents import DocumentIndex
from app.config import get_settings
from app.data.seed import company_today, ensure_fresh
from app.domain.facts import get_facts

EVALS_DIR = Path(__file__).parent
JUDGE_PASS = 4

# A string, or a list of alternatives of which one must match.
Check = str | list[str]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in cases.yaml fails loudly

    id: str
    category: str
    question: str
    history: list[str] = []
    tools: list[Check] = []
    must_include: list[Check] = []
    must_not_include: list[str] = []
    values_sql: str | None = None
    reference: str
    reference_sql: str | None = None


class Verdict(BaseModel):
    # Reasoning comes first so the judge "thinks" before it commits to a score.
    reasoning: str = Field(description="One to three sentences: what is right or wrong.")
    score: int = Field(ge=1, le=5)


JUDGE_PROMPT = PromptTemplate("""\
You are grading answers of an AI operations assistant for a logistics company.
Compare the ANSWER with the REFERENCE, which describes what a correct answer contains
(including ground-truth data from the company database where provided).

Score correctness from 1 to 5:
5 = correct and complete: every key point of the reference, nothing wrong.
4 = correct; a minor omission or imprecision that would not mislead the user.
3 = partially correct: a key point missing or wrong.
2 = mostly wrong or misleading.
1 = wrong, invents facts, or unsafe (e.g. claims to have changed data).
The reference lists the essential points; points marked "Optional" may be missing without
penalty. The assistant had access to company documents and data that you cannot see, so do
not penalize extra specific details (contacts, deadlines, procedures) unless the reference
contradicts them. Judge substance only: ignore style, length and number/date formatting.

QUESTION:
{question}

REFERENCE:
{reference}

ANSWER:
{answer}
""")


@dataclass
class CaseResult:
    id: str
    category: str
    question: str
    answer: str = ""
    tools_called: list[str] = field(default_factory=list)
    failed_tool_calls: int = 0
    routing_ok: bool = False
    facts_passed: int = 0
    facts_total: int = 0
    missing: list[str] = field(default_factory=list)
    judge_score: int | None = None
    judge_reasoning: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None

    @property
    def facts_ok(self) -> bool:
        return self.facts_passed == self.facts_total

    @property
    def judge_ok(self) -> bool:
        return self.judge_score is None or self.judge_score >= JUDGE_PASS

    @property
    def passed(self) -> bool:
        return not self.error and self.routing_ok and self.facts_ok and self.judge_ok


# ---------------------------------------------------------------- checks


# Typographic apostrophe -> ', and every dash/hyphen variant -> space (by code point).
_TYPOGRAPHY = {0x2019: "'", 0x2D: " ", 0x2010: " ", 0x2011: " ", 0x2013: " ", 0x2014: " "}


def normalize(text: str) -> str:
    """Case, thousands separators, currency signs, hyphens ("30-minute" = "30 minute")
    and typographic quotes don't matter."""
    text = text.lower().replace(",", "").replace("$", "").translate(_TYPOGRAPHY)
    return " ".join(text.split())


def contains(answer: str, check: Check) -> bool:
    options = [check] if isinstance(check, str) else check
    return any(normalize(o) in normalize(answer) for o in options)


def label(check: Check) -> str:
    return check if isinstance(check, str) else " | ".join(check)


def fill_dates(sql: str, today: date) -> str:
    return (
        sql.replace("{today}", today.isoformat())
        .replace("{tomorrow}", (today + timedelta(days=1)).isoformat())
        .replace("{month_start}", today.replace(day=1).isoformat())
    )


def query_values(db: OperationalDB, sql: str) -> list[str]:
    result = db.run(sql, row_limit=100)
    if result.error:
        raise ValueError(f"ground-truth SQL failed: {result.error}")
    return [str(v) for row in result.rows for v in row if v is not None]


def score_facts(case: EvalCase, res: CaseResult, db: OperationalDB, today: date) -> None:
    checks: list[tuple[str, bool]] = [
        (label(c), contains(res.answer, c)) for c in case.must_include
    ]
    checks += [(f"NOT {s}", not contains(res.answer, s)) for s in case.must_not_include]
    if case.values_sql:
        checks += [(f"db: {v}", contains(res.answer, v)) for v in query_values(db, fill_dates(case.values_sql, today))]  # fmt: skip
    res.facts_total = len(checks)
    res.facts_passed = sum(ok for _, ok in checks)
    res.missing = [name for name, ok in checks if not ok]


def score_routing(case: EvalCase, res: CaseResult) -> None:
    called = set(res.tools_called)
    res.routing_ok = all(
        (t in called) if isinstance(t, str) else bool(called & set(t)) for t in case.tools
    )


async def judge(llm: LLM, case: EvalCase, res: CaseResult, db: OperationalDB, today: date):
    reference = case.reference.strip()
    if case.reference_sql:
        truth = db.run(fill_dates(case.reference_sql, today), row_limit=100)
        reference += f"\n\nGround truth from the database (today is {today}):\n{truth}"
    verdict = await llm.astructured_predict(
        Verdict, JUDGE_PROMPT, question=case.question, reference=reference, answer=res.answer
    )
    res.judge_score, res.judge_reasoning = verdict.score, verdict.reasoning


# ---------------------------------------------------------------- running


async def ask(agent: OpsAgent, history: list[ChatMessage], question: str, res: CaseResult):
    """Runs one turn, recording the trace into `res`. Returns the updated history."""
    turn = TurnResult()
    res.tools_called, res.failed_tool_calls = [], 0
    async for ev in agent.stream(history, question, turn):
        match ev:
            case ToolCallEvent():
                res.tools_called.append(ev.tool)
            case ToolResultEvent() if not ev.ok:
                res.failed_tool_calls += 1
            case DoneEvent():
                res.answer, res.latency_ms = ev.answer, ev.latency_ms
                res.prompt_tokens += ev.usage.prompt_tokens
                res.completion_tokens += ev.usage.completion_tokens
                res.cost_usd += ev.usage.cost_usd or 0.0
            case ErrorEvent():
                res.error = f"{ev.code}: {ev.message}"
    return turn.history


async def run_case(case, agent, judge_llm, db, today, sem) -> CaseResult:
    res = CaseResult(id=case.id, category=case.category, question=case.question)
    async with sem:
        try:
            history: list[ChatMessage] = []
            for earlier in case.history:
                history = await ask(agent, history, earlier, res)
            await ask(agent, history, case.question, res)
            if not res.error:
                score_routing(case, res)
                score_facts(case, res, db, today)
                if judge_llm is not None:
                    await judge(judge_llm, case, res, db, today)
        except Exception as e:  # one broken case must not kill the whole run
            res.error = f"{type(e).__name__}: {e}"
    mark = "PASS" if res.passed else "FAIL"
    print(
        f"  {mark}  {case.id:<28} {res.latency_ms / 1000:5.1f}s  {','.join(res.tools_called) or '-'}"
    )
    return res


def load_cases(only: set[str] | None, category: str | None) -> list[EvalCase]:
    raw = yaml.safe_load((EVALS_DIR / "cases.yaml").read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(c) for c in raw]
    if only:
        unknown = only - {c.id for c in cases}
        if unknown:
            sys.exit(f"Unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.id in only]
    if category:
        cases = [c for c in cases if c.category == category]
    return cases


# ---------------------------------------------------------------- report


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f}%" if total else "-"


def percentile(values: list[float], q: float) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def summarize(results: list[CaseResult]) -> dict:
    n = len(results)
    judged = [r.judge_score for r in results if r.judge_score is not None]
    latencies = [r.latency_ms / 1000 for r in results if not r.error]
    return {
        "cases": n,
        "passed": sum(r.passed for r in results),
        "routing": sum(r.routing_ok for r in results),
        "facts_passed": sum(r.facts_passed for r in results),
        "facts_total": sum(r.facts_total for r in results),
        "judge_passed": sum(s >= JUDGE_PASS for s in judged),
        "judged": len(judged),
        "judge_avg": statistics.mean(judged) if judged else None,
        "errors": sum(r.error is not None for r in results),
        "p50_s": percentile(latencies, 50),
        "p95_s": percentile(latencies, 95),
        "avg_prompt_tokens": statistics.mean(r.prompt_tokens for r in results) if n else 0,
        "avg_completion_tokens": statistics.mean(r.completion_tokens for r in results) if n else 0,
        "cost_usd": sum(r.cost_usd for r in results),
    }


def render_report(results: list[CaseResult], meta: dict) -> str:
    s = summarize(results)
    judge_line = (
        f"{pct(s['judge_passed'], s['judged'])} (avg {s['judge_avg']:.2f} / 5)"
        if s["judged"]
        else "not run"
    )
    lines = [
        "# Agent eval results",
        "",
        f"Model `{meta['model']}` (reasoning: {meta['reasoning']}) · judge `{meta['judge']}` · "
        f"{s['cases']} cases · data as of {meta['today']} · run {meta['run_at']}",
        "",
        "Generated by `uv run python -m evals.run` — do not edit by hand.",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| **Cases passed** (routing + facts + judge) | **{s['passed']}/{s['cases']} ({pct(s['passed'], s['cases'])})** |",
        f"| Tool routing accuracy | {pct(s['routing'], s['cases'])} |",
        f"| Fact checks (incl. live DB values) | {pct(s['facts_passed'], s['facts_total'])} ({s['facts_passed']}/{s['facts_total']}) |",
        f"| LLM judge: correct (score ≥ {JUDGE_PASS}) | {judge_line} |",
        f"| Latency p50 / p95 | {s['p50_s']:.1f} s / {s['p95_s']:.1f} s |",
        f"| Avg tokens per answer (in / out) | {s['avg_prompt_tokens']:,.0f} / {s['avg_completion_tokens']:,.0f} |",
        f"| Agent cost, whole run | ${s['cost_usd']:.4f} |",
        f"| Errors | {s['errors']} |",
        "",
        "## By category",
        "",
        "| Category | Cases | Passed | Routing | Facts | Judge avg |",
        "|---|---|---|---|---|---|",
    ]  # fmt: skip
    for cat in dict.fromkeys(r.category for r in results):
        c = summarize([r for r in results if r.category == cat])
        avg = f"{c['judge_avg']:.1f}" if c["judge_avg"] is not None else "-"
        lines.append(
            f"| {cat} | {c['cases']} | {c['passed']} | {pct(c['routing'], c['cases'])} | "
            f"{pct(c['facts_passed'], c['facts_total'])} | {avg} |"
        )

    lines += [
        "",
        "## Cases",
        "",
        "| | Case | Tools called | Routing | Facts | Judge | Latency | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        tools = ", ".join(f"`{t}`" for t in r.tools_called) or "—"
        judge_cell = str(r.judge_score) if r.judge_score is not None else "—"
        lines.append(
            f"| {'✅' if r.passed else '❌'} | {r.id} | {tools} | {'✓' if r.routing_ok else '✗'} | "
            f"{r.facts_passed}/{r.facts_total} | {judge_cell} | {r.latency_ms / 1000:.1f} s | "
            f"${r.cost_usd:.4f} |"
        )

    failures = [r for r in results if not r.passed]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            lines += [f"### {r.id}", "", f"**Q:** {r.question}", ""]
            if r.error:
                lines.append(f"- Error: `{r.error}`")
            if not r.routing_ok and not r.error:
                lines.append(f"- Routing: called {r.tools_called or 'no tools'}")
            if r.missing:
                lines.append(f"- Failed checks: {'; '.join(f'`{m}`' for m in r.missing)}")
            if r.judge_score is not None and not r.judge_ok:
                lines.append(f"- Judge {r.judge_score}/5: {r.judge_reasoning}")
            excerpt = " ".join(r.answer.split())[:700]
            lines += ["", f"> {excerpt}{'…' if len(r.answer) > 700 else ''}", ""]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- main


async def main(args: argparse.Namespace) -> int:
    settings, facts = get_settings(), get_facts()
    cases = load_cases(set(args.only.split(",")) if args.only else None, args.category)
    if not cases:
        sys.exit("No cases selected.")

    ensure_fresh(settings.db_path, facts)
    today = company_today(facts)
    db = OperationalDB(settings.db_path, settings.sql_row_limit)
    agent = OpsAgent(
        settings, facts, build_llm(settings), DocumentIndex.load_or_build(settings), db
    )
    judge_model = args.judge_model or settings.llm_model
    judge_llm = (
        None if args.no_judge else build_llm(settings.model_copy(update={"llm_model": judge_model}))
    )

    print(f"Running {len(cases)} cases with {settings.llm_model} (concurrency {args.concurrency})")
    started = time.perf_counter()
    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(run_case(c, agent, judge_llm, db, today, sem) for c in cases))

    meta = {
        "model": settings.llm_model,
        "reasoning": settings.llm_reasoning_effort or "default",
        "judge": "off" if args.no_judge else judge_model,
        "today": today.isoformat(),
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    report = render_report(results, meta)
    out = EVALS_DIR / "results" / "agent.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")

    raw_dir = settings.var_dir / "evals"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = raw_dir / f"agent-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    raw.write_text(
        json.dumps({"meta": meta, "summary": summarize(results),
                    "results": [asdict(r) for r in results]}, indent=2),
        encoding="utf-8",
    )  # fmt: skip

    s = summarize(results)
    rate = 100 * s["passed"] / s["cases"]
    print(
        f"\n{s['passed']}/{s['cases']} passed ({rate:.0f}%) · routing {pct(s['routing'], s['cases'])}"
        f" · ${s['cost_usd']:.4f} · {time.perf_counter() - started:.0f}s wall"
    )
    print(f"Report: {out.relative_to(EVALS_DIR.parent)}   Raw: {raw}")
    return 1 if args.fail_under is not None and rate < args.fail_under else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--only", help="comma-separated case ids")
    p.add_argument("--category", help="run one category only")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--no-judge", action="store_true", help="skip the LLM judge (cheaper)")
    p.add_argument("--judge-model", help="model for the judge (default: LLM_MODEL)")
    p.add_argument("--fail-under", type=float, help="exit 1 if the pass rate is below this %%")
    return p.parse_args()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main(parse_args())))
