"""`quote_shipment` tool: thin adapter over the deterministic pricing domain.

LLMs are unreliable at arithmetic, so the model never computes a price itself:
it extracts the parameters and this tool returns an exact, itemized quote.
"""

from dataclasses import dataclass, field

from app.agent.events import QuoteLine, QuoteTrace
from app.domain import pricing
from app.domain.facts import Facts


@dataclass
class QuoteResult:
    params: dict
    quotes: list[pricing.Quote] = field(default_factory=list)
    error: str | None = None

    def __str__(self) -> str:
        if self.error:
            return f"Cannot quote: {self.error}"
        lines = [
            f"{q.carrier_name} ({q.carrier_code}), {q.mode}: total ${q.total_usd:,.2f} "
            f"= linehaul ${q.linehaul_usd:,.2f} ({q.weight_lb:g} lb x ${q.rate_per_lb}/lb, "
            f"min charge applied if higher) + fuel ${q.fuel_surcharge_usd:,.2f}"
            + (f" + hazmat ${q.hazmat_fee_usd:,.2f}" if q.hazmat_fee_usd else "")
            + (f" + accessorials ${q.accessorials_usd:,.2f}" if q.accessorials_usd else "")
            for q in self.quotes
        ]
        return "Quotes, cheapest first:\n" + "\n".join(lines)

    def to_ui(self) -> QuoteTrace:
        return QuoteTrace(
            params=self.params,
            quotes=[QuoteLine(**q.to_dict()) for q in self.quotes],
            error=self.error,
        )


def make_quote_fn(facts: Facts, max_results: int = 5):
    def quote_shipment(
        zone: str,
        weight_lb: float,
        hazmat: bool = False,
        liftgate: bool = False,
        residential: bool = False,
        carrier_code: str | None = None,
    ) -> QuoteResult:
        """Calculate exact freight prices using HPL's contracted rates and surcharges.

        Always use this for any price or cost estimate; never compute prices yourself.
        Returns quotes for every eligible carrier and mode (cheapest first), or for one
        carrier if carrier_code is given. Mode is chosen automatically from the weight.

        Args:
            zone: Destination zone by distance from the origin facility:
                Z1 under 100 miles, Z2 100-300, Z3 300-600, Z4 over 600.
            weight_lb: Total shipment weight in pounds.
            hazmat: True if the shipment contains hazardous materials (incl. lithium batteries).
            liftgate: True if liftgate service is needed at delivery.
            residential: True if delivering to a residential address.
            carrier_code: Optional carrier code (e.g. 'PRL') to quote a single carrier.
        """
        params = {
            "zone": zone,
            "weight_lb": weight_lb,
            "hazmat": hazmat,
            "liftgate": liftgate,
            "residential": residential,
            "carrier_code": carrier_code,
        }
        try:
            zone = zone.strip().upper()
            if carrier_code:
                modes = pricing.allowed_modes(facts, weight_lb)
                quotes, last_error = [], None
                for mode in modes:
                    try:
                        quotes.append(
                            pricing.quote(
                                facts, carrier_code.strip().upper(), mode, zone, weight_lb,
                                hazmat, liftgate, residential,
                            )
                        )  # fmt: skip
                    except pricing.PricingError as e:
                        last_error = e
                if not quotes:
                    raise last_error or pricing.PricingError("no mode accepts this weight")
            else:
                quotes = pricing.quote_all(facts, zone, weight_lb, hazmat, liftgate, residential)
            return QuoteResult(params, sorted(quotes, key=lambda q: q.total_usd)[:max_results])
        except pricing.PricingError as e:
            return QuoteResult(params, error=str(e))

    return quote_shipment
