import unittest

from king_county_food_safety import sql


class SQLTests(unittest.TestCase):
    def test_and_omits_empty_clauses(self) -> None:
        self.assertEqual(
            sql.and_("", "Business_Status = 'Active'", "Business_Grade = 'Good'"),
            "(Business_Status = 'Active') AND (Business_Grade = 'Good')",
        )

    def test_contains_uppercases_and_escapes_quotes(self) -> None:
        self.assertEqual(sql.contains("Business_Name", "Dick's"), "UPPER(Business_Name) LIKE '%DICK''S%'")

    def test_string_literal_escapes_quotes(self) -> None:
        self.assertEqual(sql.string_literal("Bob's Burgers"), "'Bob''s Burgers'")


if __name__ == "__main__":
    unittest.main()
