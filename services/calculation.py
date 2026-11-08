"""Exact Decimal-based tax estimate calculations."""

from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP

CALCULATION_ALGORITHM_VERSION = "1"
ROUNDING_POLICY = "ROUND_HALF_UP to 0.01 for each monetary component"


def calculate_estimate(
    base: Decimal,
    rates: Mapping[str, Decimal | None],
    scenario: str,
) -> dict[str, Decimal | None]:
    """Calculate federal, state, and municipal estimates for one scenario."""
    if not isinstance(base, Decimal):
        raise TypeError("base must be a Decimal")
    if not base.is_finite() or base < 0:
        raise ValueError("base must be finite and non-negative")
    if not isinstance(rates, Mapping):
        raise TypeError("rates must be a mapping")
    if scenario not in ("nacional", "importado"):
        raise ValueError("scenario must be 'nacional' or 'importado'")

    federal_key = "Nacional" if scenario == "nacional" else "Importado"
    source_keys = (federal_key, "Estadual", "Municipal")
    components: dict[str, Decimal | None] = {}
    selected_rates: list[Decimal] = []

    for output_key, source_key in zip(
        ("Federal", "Estadual", "Municipal"), source_keys
    ):
        rate = rates.get(source_key)
        if rate is not None:
            if not isinstance(rate, Decimal):
                raise TypeError(f"rate {source_key!r} must be a Decimal or None")
            if not rate.is_finite() or rate < 0:
                raise ValueError(f"rate {source_key!r} must be finite and non-negative")
            selected_rates.append(rate)
            components[output_key] = (base * rate / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            components[output_key] = None

    component_values = tuple(components.values())
    if any(value is None for value in component_values):
        total = None
        percentual_total = None
    else:
        total = sum(component_values, Decimal("0"))
        percentual_total = sum(selected_rates, Decimal("0"))

    return {
        **components,
        "total": total,
        "percentual_total": percentual_total,
    }
