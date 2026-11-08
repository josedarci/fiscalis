import unittest
from decimal import Decimal

from services.calculation import (
    CALCULATION_ALGORITHM_VERSION,
    ROUNDING_POLICY,
    calculate_estimate,
)


class CalculateEstimateTests(unittest.TestCase):
    def test_national_scenario_uses_national_federal_rate(self):
        result = calculate_estimate(
            Decimal("1000"),
            {
                "Nacional": Decimal("12.345"),
                "Importado": Decimal("20"),
                "Estadual": Decimal("18.25"),
                "Municipal": Decimal("2.125"),
            },
            "nacional",
        )

        self.assertEqual(
            result,
            {
                "Federal": Decimal("123.45"),
                "Estadual": Decimal("182.50"),
                "Municipal": Decimal("21.25"),
                "total": Decimal("327.20"),
                "percentual_total": Decimal("32.720"),
            },
        )

    def test_imported_scenario_uses_imported_federal_rate(self):
        result = calculate_estimate(
            Decimal("200"),
            {
                "Nacional": Decimal("10"),
                "Importado": Decimal("15.75"),
                "Estadual": Decimal("5"),
                "Municipal": Decimal("0"),
            },
            "importado",
        )

        self.assertEqual(
            result,
            {
                "Federal": Decimal("31.50"),
                "Estadual": Decimal("10.00"),
                "Municipal": Decimal("0.00"),
                "total": Decimal("41.50"),
                "percentual_total": Decimal("20.75"),
            },
        )

    def test_missing_rates_are_not_replaced_with_zero(self):
        result = calculate_estimate(
            Decimal("100"),
            {"Nacional": Decimal("0"), "Estadual": None},
            "nacional",
        )

        self.assertEqual(result["Federal"], Decimal("0.00"))
        self.assertIsNone(result["Estadual"])
        self.assertIsNone(result["Municipal"])
        self.assertIsNone(result["total"])
        self.assertIsNone(result["percentual_total"])

    def test_zero_rates_are_valid_and_produce_zero_totals(self):
        result = calculate_estimate(
            Decimal("100"),
            {
                "Nacional": Decimal("0"),
                "Estadual": Decimal("0"),
                "Municipal": Decimal("0"),
            },
            "nacional",
        )

        self.assertEqual(result["Federal"], Decimal("0.00"))
        self.assertEqual(result["Estadual"], Decimal("0.00"))
        self.assertEqual(result["Municipal"], Decimal("0.00"))
        self.assertEqual(result["total"], Decimal("0.00"))
        self.assertEqual(result["percentual_total"], Decimal("0"))

    def test_half_cent_rounds_up_for_each_component_before_total(self):
        result = calculate_estimate(
            Decimal("1"),
            {
                "Nacional": Decimal("0.5"),
                "Estadual": Decimal("0.5"),
                "Municipal": Decimal("0.5"),
            },
            "nacional",
        )

        self.assertEqual(result["Federal"], Decimal("0.01"))
        self.assertEqual(result["Estadual"], Decimal("0.01"))
        self.assertEqual(result["Municipal"], Decimal("0.01"))
        self.assertEqual(result["total"], Decimal("0.03"))

    def test_percentage_precision_is_preserved(self):
        result = calculate_estimate(
            Decimal("100"),
            {
                "Nacional": Decimal("1.234567"),
                "Estadual": Decimal("2.00001"),
                "Municipal": Decimal("0.00009"),
            },
            "nacional",
        )

        self.assertEqual(result["Federal"], Decimal("1.23"))
        self.assertEqual(result["percentual_total"], Decimal("3.234667"))

    def test_invalid_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_estimate(Decimal("100"), {}, "combined")

    def test_invalid_base_and_rates_are_rejected(self):
        with self.assertRaises(TypeError):
            calculate_estimate(100, {}, "nacional")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            calculate_estimate(Decimal("-1"), {}, "nacional")
        with self.assertRaises(ValueError):
            calculate_estimate(Decimal("NaN"), {}, "nacional")
        with self.assertRaises(TypeError):
            calculate_estimate(
                Decimal("100"), {"Nacional": "5"}, "nacional"  # type: ignore[dict-item]
            )
        with self.assertRaises(ValueError):
            calculate_estimate(
                Decimal("100"), {"Nacional": Decimal("Infinity")}, "nacional"
            )
        with self.assertRaises(ValueError):
            calculate_estimate(
                Decimal("100"), {"Nacional": Decimal("-0.01")}, "nacional"
            )

    def test_calculation_metadata_is_defined(self):
        self.assertTrue(CALCULATION_ALGORITHM_VERSION)
        self.assertIn("ROUND_HALF_UP", ROUNDING_POLICY)


if __name__ == "__main__":
    unittest.main()
