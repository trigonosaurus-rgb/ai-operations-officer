"""Pricing is pure Python over facts.yaml, so it can be tested exactly — that is the
point of keeping arithmetic out of the LLM."""

import pytest

from app.agent.tools.pricing import make_quote_fn
from app.domain import pricing
from app.domain.pricing import PricingError


def test_quote_matches_the_carrier_agreement_formula(facts):
    """Golden example, computed by hand from HPL-LEG-001 §5:
    3,200 lb x $0.26/lb = $832.00 linehaul; fuel 18.5% = $153.92; liftgate $75."""
    q = pricing.quote(facts, "PRL", "LTL", "Z3", 3200, liftgate=True)
    assert q.rate_per_lb == 0.26
    assert q.linehaul_usd == 832.00
    assert q.fuel_surcharge_usd == 153.92
    assert q.accessorials_usd == 75.00
    assert q.total_usd == 1060.92


def test_minimum_charge_applies_before_surcharges(facts):
    q = pricing.quote(facts, "PRL", "LTL", "Z1", 160)  # 160 x 0.14 = $22.40 < $145 minimum
    assert q.linehaul_usd == facts["base_rates"]["LTL"]["min_charge"] == 145.00
    assert q.fuel_surcharge_usd == pytest.approx(145 * 0.185, abs=0.01)


def test_fuel_surcharge_is_not_applied_to_accessorials(facts):
    plain = pricing.quote(facts, "PRL", "LTL", "Z2", 2000)
    extras = pricing.quote(facts, "PRL", "LTL", "Z2", 2000, True, True, True)
    assert extras.fuel_surcharge_usd == plain.fuel_surcharge_usd
    assert extras.total_usd == pytest.approx(plain.total_usd + 85 + 75 + 45)


def test_carrier_rate_factor_is_applied(facts):
    assert pricing.rate_per_lb(facts, "LKX", "LTL", "Z2") == round(0.19 * 0.92, 4)


@pytest.mark.parametrize(
    ("weight", "modes"),
    [(10, ["PARCEL"]), (150, ["PARCEL"]), (151, ["LTL"]), (5000, ["LTL", "FTL"]),
     (10_000, ["LTL", "FTL"]), (10_001, ["FTL"]), (44_000, ["FTL"]), (44_001, [])],
)  # fmt: skip
def test_mode_follows_weight_limits(facts, weight, modes):
    assert pricing.allowed_modes(facts, weight) == modes


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("NOPE", "LTL", "Z1", 500), "Unknown carrier"),
        (("PRL", "AIR", "Z1", 500), "Unknown mode"),
        (("PRL", "LTL", "Z9", 500), "Unknown zone"),
        (("PRL", "LTL", "Z1", 50), "outside LTL limits"),
        (("CSC", "LTL", "Z3", 500), "does not offer LTL service to zone Z3"),
        (("LKX", "LTL", "Z1", 500, True), "not hazmat-certified"),
    ],
)
def test_unpriceable_requests_raise_a_readable_error(facts, args, message):
    with pytest.raises(PricingError, match=message):
        pricing.quote(facts, *args)


def test_quote_all_is_sorted_and_respects_hazmat_certification(facts):
    quotes = pricing.quote_all(facts, "Z2", 650, hazmat=True)
    totals = [q.total_usd for q in quotes]
    assert totals == sorted(totals)
    certified = {c["code"] for c in facts["carriers"] if c["hazmat_certified"]}
    assert {q.carrier_code for q in quotes} <= certified
    assert all(q.hazmat_fee_usd == 85.0 for q in quotes)


def test_quote_all_explains_when_nothing_fits(facts):
    with pytest.raises(PricingError, match="No transport mode"):
        pricing.quote_all(facts, "Z1", 50_000)


# --- the agent tool wrapped around the domain ---


def test_tool_normalizes_llm_input_and_returns_cheapest_first(facts):
    quote_shipment = make_quote_fn(facts)
    result = quote_shipment(zone=" z3 ", weight_lb=3200, liftgate=True)
    assert result.error is None
    assert result.quotes[0].total_usd == min(q.total_usd for q in result.quotes)
    assert str(result).startswith("Quotes, cheapest first:")
    assert result.to_ui().quotes[0].carrier_code == result.quotes[0].carrier_code


def test_tool_quotes_a_single_carrier_across_modes(facts):
    result = make_quote_fn(facts)(zone="Z2", weight_lb=6000, carrier_code="prl")
    assert {(q.carrier_code, q.mode) for q in result.quotes} == {("PRL", "LTL"), ("PRL", "FTL")}


def test_tool_reports_errors_to_the_llm_instead_of_raising(facts):
    result = make_quote_fn(facts)(zone="Z1", weight_lb=500, hazmat=True, carrier_code="LKX")
    assert result.quotes == []
    assert str(result) == "Cannot quote: Lakeshore Express is not hazmat-certified."
    assert result.to_ui().error is not None
