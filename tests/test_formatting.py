import contextlib
import io
import json
import unittest

from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.formatting import (
    coordinate_display,
    date_time,
    display,
    emit_records,
    inspection_violation_records,
    print_facility_detail,
    print_json,
    print_table,
)
from king_county_food_safety.models import (
    FacilityDetail,
    FacilityRecord,
    Feature,
    Geometry,
    InspectionRecord,
    InspectionWithViolations,
)


class FormattingTests(unittest.TestCase):
    def test_jsonl_prints_one_projected_record_per_line(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                [
                    {
                        "business_record_id": "A",
                        "business_name": "Alpha",
                        "rating": "Good",
                    },
                    {
                        "business_record_id": "B",
                        "business_name": "Beta",
                        "rating": "Excellent",
                    },
                ],
                output_format="jsonl",
                default_fields=["business_record_id", "business_name", "rating"],
                fields=["business_record_id", "rating"],
            )

        lines = stream.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            json.loads(lines[0]), {"business_record_id": "A", "rating": "Good"}
        )
        self.assertEqual(
            json.loads(lines[1]), {"business_record_id": "B", "rating": "Excellent"}
        )

    def test_csv_prints_projected_header_and_rows(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                [
                    {
                        "business_record_id": "A",
                        "business_name": "Alpha",
                        "rating": "Good",
                    },
                    {
                        "business_record_id": "B",
                        "business_name": "Beta, LLC",
                        "rating": "Excellent",
                    },
                ],
                output_format="csv",
                default_fields=["business_record_id", "business_name", "rating"],
                fields=["business_record_id", "business_name"],
            )

        self.assertEqual(
            stream.getvalue(),
            'business_record_id,business_name\nA,Alpha\nB,"Beta, LLC"\n',
        )

    def test_tsv_prints_projected_header_and_rows(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                [{"inspection_serial_number": "PFE-1", "inspection_score": 5}],
                output_format="tsv",
                default_fields=["inspection_serial_number", "inspection_score"],
            )

        self.assertEqual(
            stream.getvalue(), "inspection_serial_number\tinspection_score\nPFE-1\t5\n"
        )

    def test_unknown_field_fails_with_available_fields(self) -> None:
        with self.assertRaises(FoodSafetyError):
            emit_records(
                [{"rating": "Good"}],
                output_format="json",
                default_fields=["rating"],
                fields=["missing"],
            )

    def test_table_output_and_all_fields_projection(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                [{"rating": "Good", "extra": None, "score": 1.25}],
                output_format="table",
                default_fields=["rating"],
                fields=["*"],
            )

        output = stream.getvalue()
        self.assertIn("rating", output)
        self.assertIn("extra", output)
        self.assertIn("1.25", output)

    def test_display_coordinate_and_date_helpers(self) -> None:
        self.assertEqual(coordinate_display(None), "-")
        self.assertEqual(
            coordinate_display(Geometry(x=-122.3, y=47.6)), "47.600000, -122.300000"
        )
        self.assertIsNone(date_time(None))
        self.assertEqual(display(None), "-")
        self.assertEqual(display(""), "-")
        self.assertEqual(display(5), "5")

    def test_inspection_violation_records_handles_missing_violations(self) -> None:
        records = inspection_violation_records(
            [InspectionWithViolations(inspection=_inspection(), violations=[])]
        )

        self.assertIsNone(records[0]["violation_type"])

    def test_print_facility_detail_human_table_and_machine_projection(self) -> None:
        detail = FacilityDetail(
            facility=_facility(),
            inspections=[InspectionWithViolations(_inspection(), [])],
        )
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            print_facility_detail(detail, output_format="table")

        output = stream.getvalue()
        self.assertIn("Business Record ID", output)
        self.assertIn("inspection_date", output)

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            print_facility_detail(
                detail, output_format="json", fields=["business_record_id"]
            )
        self.assertEqual(
            json.loads(stream.getvalue()), [{"business_record_id": "PFE-1"}]
        )

    def test_print_json_and_table_empty_rows(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            print_json({"ok": True})
        self.assertEqual(json.loads(stream.getvalue()), {"ok": True})

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            print_table(["name"], [])
        self.assertEqual(stream.getvalue(), "No records found.\n")


def _facility() -> Feature[FacilityRecord]:
    return Feature(
        FacilityRecord(
            business_address=None,
            business_city=None,
            business_establishment_description=None,
            business_grade="Good",
            business_latitude=None,
            business_longitude=None,
            business_name="Alpha",
            business_phone=None,
            business_program_identifier="",
            business_record_id="PFE-1",
            business_status="Active",
            business_zip="98105",
            load_date_milliseconds=1781420580000,
            object_id=1,
            parcel_latitude=None,
            parcel_longitude=None,
            parcel_number=None,
        ),
        Geometry(x=-122.3, y=47.6),
    )


def _inspection() -> Feature[InspectionRecord]:
    return Feature(
        InspectionRecord(
            business_record_id="PFE-1",
            inspection_business_name="Alpha",
            inspection_date="2025-01-01",
            inspection_result="Satisfactory",
            inspection_score=0,
            inspection_serial_number="S1",
            inspection_type="Routine Inspection/Field Review",
            load_date_milliseconds=None,
            object_id=1,
        )
    )


if __name__ == "__main__":
    unittest.main()
