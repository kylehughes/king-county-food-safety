import unittest

from kc_food_safety.api import FoodSafetyAPI


class FoodSafetyAPITests(unittest.TestCase):
    def test_unique_non_empty_preserves_order(self) -> None:
        self.assertEqual(FoodSafetyAPI._unique_non_empty([" A ", "", "B", "A", "C"]), ["A", "B", "C"])

    def test_chunks_split_values(self) -> None:
        self.assertEqual(FoodSafetyAPI._chunks(["A", "B", "C", "D", "E"], 2), [["A", "B"], ["C", "D"], ["E"]])


if __name__ == "__main__":
    unittest.main()
