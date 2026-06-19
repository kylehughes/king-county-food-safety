import contextlib
import io
import json
import unittest

from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.formatting import emit_records


class FormattingTests(unittest.TestCase):
    def test_jsonl_prints_one_projected_record_per_line(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                [
                    {"business_record_id": "A", "business_name": "Alpha", "rating": "Good"},
                    {"business_record_id": "B", "business_name": "Beta", "rating": "Excellent"},
                ],
                output_format="jsonl",
                default_fields=["business_record_id", "business_name", "rating"],
                fields=["business_record_id", "rating"],
            )

        lines = stream.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"business_record_id": "A", "rating": "Good"})
        self.assertEqual(json.loads(lines[1]), {"business_record_id": "B", "rating": "Excellent"})

    def test_tsv_prints_projected_header_and_rows(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                [{"inspection_serial_number": "PFE-1", "inspection_score": 5}],
                output_format="tsv",
                default_fields=["inspection_serial_number", "inspection_score"],
            )

        self.assertEqual(stream.getvalue(), "inspection_serial_number\tinspection_score\nPFE-1\t5\n")

    def test_unknown_field_fails_with_available_fields(self) -> None:
        with self.assertRaises(FoodSafetyError):
            emit_records(
                [{"rating": "Good"}],
                output_format="json",
                default_fields=["rating"],
                fields=["missing"],
            )


if __name__ == "__main__":
    unittest.main()
