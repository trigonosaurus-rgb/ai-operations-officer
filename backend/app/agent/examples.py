"""Curated starter questions shown in the UI. Each one exercises a different skill."""

EXAMPLES: list[dict] = [
    {
        "category": "Operations",
        "questions": [
            "Can I book a dock at CHI1 tomorrow morning?",
            "Which shipments are delayed right now, and why?",
            "What inventory is below its reorder point at IND1?",
        ],
    },
    {
        "category": "Policy",
        "questions": [
            "A driver arrives 45 minutes late for his appointment. What happens?",
            "How long do we have to report concealed damage, and what's the liability limit?",
            "Can we ship lithium battery modules out of Milwaukee?",
        ],
    },
    {
        "category": "Pricing",
        "questions": [
            "Quote a 3,200 lb LTL shipment to St. Louis with liftgate delivery.",
            "What's the cheapest way to ship 650 lb of paint thinner to Detroit?",
        ],
    },
    {
        "category": "Audit & SLA",
        "questions": [
            "Did any hazmat shipments go out with a carrier that isn't hazmat-certified?",
            "Are we meeting our on-time SLA this month? Do any weather holds affect the number?",
            "Which carrier performs worst on time, and what does the carrier agreement say about it?",
        ],
    },
]
