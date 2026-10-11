"""The eval scorers are code too: a bug here would silently skew every metric."""

from datetime import date

import pytest

from evals.run import CaseResult, EvalCase, contains, fill_dates, load_cases, score_routing


@pytest.mark.parametrize(
    ("answer", "check"),
    [
        ("Total: **$1,364.28**", "1364.28"),
        ("a 30" + chr(0x2011) + "minute grace period", "30 min"),
        ("I have READ-ONLY access", ["read only", "cannot"]),
        ("The driver" + chr(0x2019) + "s fee", "driver's"),
    ],
)
def test_fact_checks_ignore_formatting(answer, check):
    assert contains(answer, check)


def test_fact_check_still_detects_wrong_values():
    assert not contains("Total: $1,346.28", "1364.28")


def test_routing_requires_all_tools_and_any_of_alternatives():
    case = EvalCase(id="x", category="c", question="q", reference="r",
                    tools=["search_documents", ["query_database", "quote_shipment"]])  # fmt: skip
    res = CaseResult(id="x", category="c", question="q")

    res.tools_called = ["search_documents", "quote_shipment"]
    score_routing(case, res)
    assert res.routing_ok

    res.tools_called = ["query_database"]
    score_routing(case, res)
    assert not res.routing_ok


def test_date_placeholders():
    sql = fill_dates("'{today}' '{tomorrow}' '{month_start}'", date(2026, 10, 31))
    assert sql == "'2026-10-31' '2026-11-01' '2026-10-01'"


def test_golden_cases_file_is_valid():
    cases = load_cases(None, None)
    assert len(cases) >= 25
    assert len({c.id for c in cases}) == len(cases)
