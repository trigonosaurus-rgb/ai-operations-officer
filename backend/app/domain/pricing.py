"""Deterministic freight pricing.

Pure functions over the fact sheet — no LLM, no I/O. Used both by the database
seed (historical freight costs) and by the agent's `quote_shipment` tool, so a
price the agent quotes is always computed exactly the way invoices are.
"""

from dataclasses import asdict, dataclass

from app.domain.facts import Facts


class PricingError(ValueError):
    """Raised for requests that cannot be priced (message is shown to the agent)."""


@dataclass(frozen=True)
class Quote:
    carrier_code: str
    carrier_name: str
    mode: str
    zone: str
    weight_lb: float
    rate_per_lb: float
    linehaul_usd: float
    fuel_surcharge_usd: float
    hazmat_fee_usd: float
    accessorials_usd: float
    total_usd: float

    def to_dict(self) -> dict:
        return asdict(self)


def rate_per_lb(facts: Facts, carrier_code: str, mode: str, zone: str) -> float:
    base = facts["base_rates"][mode][zone]
    return round(base * facts["rate_factors"][carrier_code], 4)


def allowed_modes(facts: Facts, weight_lb: float) -> list[str]:
    return [
        mode
        for mode, limits in facts["modes"].items()
        if limits["min_lb"] <= weight_lb <= limits["max_lb"]
    ]


def eligible_carriers(facts: Facts, mode: str, zone: str, hazmat: bool) -> list[dict]:
    return [
        c
        for c in facts["carriers"]
        if mode in c["modes"] and zone in c["zones"] and (c["hazmat_certified"] or not hazmat)
    ]


def quote(
    facts: Facts,
    carrier_code: str,
    mode: str,
    zone: str,
    weight_lb: float,
    hazmat: bool = False,
    liftgate: bool = False,
    residential: bool = False,
) -> Quote:
    carriers = {c["code"]: c for c in facts["carriers"]}
    carrier = carriers.get(carrier_code)
    if carrier is None:
        raise PricingError(f"Unknown carrier '{carrier_code}'. Known: {', '.join(carriers)}.")
    if mode not in facts["modes"]:
        raise PricingError(f"Unknown mode '{mode}'. Use one of: {', '.join(facts['modes'])}.")
    if zone not in facts["base_rates"][mode]:
        raise PricingError(f"Unknown zone '{zone}'. Use Z1, Z2, Z3 or Z4.")
    if mode not in allowed_modes(facts, weight_lb):
        limits = facts["modes"][mode]
        raise PricingError(
            f"{weight_lb:g} lb is outside {mode} limits ({limits['min_lb']}-{limits['max_lb']} lb)."
        )
    if mode not in carrier["modes"] or zone not in carrier["zones"]:
        raise PricingError(f"{carrier['name']} does not offer {mode} service to zone {zone}.")
    if hazmat and not carrier["hazmat_certified"]:
        raise PricingError(f"{carrier['name']} is not hazmat-certified.")

    surcharges = facts["surcharges"]
    rate = rate_per_lb(facts, carrier_code, mode, zone)
    linehaul = max(weight_lb * rate, facts["base_rates"][mode]["min_charge"])
    fuel = linehaul * surcharges["fuel_pct"] / 100
    hazmat_fee = surcharges["hazmat_fee_usd"] if hazmat else 0.0
    accessorials = (surcharges["liftgate_fee_usd"] if liftgate else 0.0) + (
        surcharges["residential_fee_usd"] if residential else 0.0
    )
    total = linehaul + fuel + hazmat_fee + accessorials

    return Quote(
        carrier_code=carrier_code,
        carrier_name=carrier["name"],
        mode=mode,
        zone=zone,
        weight_lb=weight_lb,
        rate_per_lb=rate,
        linehaul_usd=round(linehaul, 2),
        fuel_surcharge_usd=round(fuel, 2),
        hazmat_fee_usd=round(hazmat_fee, 2),
        accessorials_usd=round(accessorials, 2),
        total_usd=round(total, 2),
    )


def quote_all(
    facts: Facts,
    zone: str,
    weight_lb: float,
    hazmat: bool = False,
    liftgate: bool = False,
    residential: bool = False,
) -> list[Quote]:
    """Quotes every eligible carrier/mode combination, cheapest first."""
    modes = allowed_modes(facts, weight_lb)
    if not modes:
        raise PricingError(f"No transport mode accepts a {weight_lb:g} lb shipment.")
    quotes = [
        quote(facts, c["code"], mode, zone, weight_lb, hazmat, liftgate, residential)
        for mode in modes
        for c in eligible_carriers(facts, mode, zone, hazmat)
    ]
    if not quotes:
        reason = " hazmat-certified" if hazmat else ""
        raise PricingError(f"No{reason} carrier serves zone {zone} for {weight_lb:g} lb.")
    return sorted(quotes, key=lambda q: q.total_usd)
