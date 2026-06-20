import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.formatting import emit_records
from king_county_food_safety.raw import (
    compact_diff_record,
    default_key_field,
    diff_records,
    payload_records,
    read_records,
)


class RawPayloadTests(unittest.TestCase):
    def test_payload_records_flatten_feature_attributes_and_geometry(self) -> None:
        records = payload_records(
            {
                "features": [
                    {
                        "attributes": {"OBJECTID": 1, "Business_Name": "Alpha"},
                        "geometry": {
                            "x": -122.3,
                            "y": 47.6,
                            "rings": [[[0, 0]]],
                            "paths": [[[1, 1]]],
                        },
                    }
                ]
            }
        )

        self.assertEqual(
            records,
            [
                {
                    "OBJECTID": 1,
                    "Business_Name": "Alpha",
                    "geometry_x": -122.3,
                    "geometry_y": 47.6,
                    "geometry_rings": [[[0, 0]]],
                    "geometry_paths": [[[1, 1]]],
                }
            ],
        )

    def test_payload_records_support_count_ids_and_invalid_features(self) -> None:
        self.assertEqual(payload_records({"count": 2}), [{"count": 2}])
        self.assertEqual(
            payload_records({"objectIds": [1, 2]}), [{"object_id": 1}, {"object_id": 2}]
        )
        with self.assertRaises(FoodSafetyError):
            payload_records({"features": [{"attributes": []}]})

    def test_raw_payload_records_export_as_jsonl(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                self._records(),
                output_format="jsonl",
                default_fields=["OBJECTID", "Business_Name"],
            )

        lines = stream.getvalue().splitlines()
        self.assertEqual(
            json.loads(lines[0]), {"OBJECTID": 1, "Business_Name": "Alpha"}
        )
        self.assertEqual(
            json.loads(lines[1]), {"OBJECTID": 2, "Business_Name": "Beta, LLC"}
        )

    def test_raw_payload_records_export_as_csv(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                self._records(),
                output_format="csv",
                default_fields=["OBJECTID", "Business_Name"],
            )

        self.assertEqual(
            stream.getvalue(), 'OBJECTID,Business_Name\n1,Alpha\n2,"Beta, LLC"\n'
        )

    def test_raw_payload_records_export_as_tsv(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit_records(
                self._records(),
                output_format="tsv",
                default_fields=["OBJECTID", "Business_Name"],
            )

        self.assertEqual(
            stream.getvalue(), "OBJECTID\tBusiness_Name\n1\tAlpha\n2\tBeta, LLC\n"
        )

    def test_read_records_supports_empty_json_array_jsonl_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            self.assertEqual(read_records(str(empty)), [])

            array = Path(directory) / "array.json"
            array.write_text('[{"OBJECTID": 1}]', encoding="utf-8")
            self.assertEqual(read_records(str(array)), [{"OBJECTID": 1}])

            jsonl = Path(directory) / "records.jsonl"
            jsonl.write_text('{"OBJECTID": 1}\n{"OBJECTID": 2}\n', encoding="utf-8")
            self.assertEqual(
                read_records(str(jsonl)), [{"OBJECTID": 1}, {"OBJECTID": 2}]
            )

            not_array = Path(directory) / "not-array.json"
            not_array.write_text('{"OBJECTID": 1}', encoding="utf-8")
            self.assertEqual(read_records(str(not_array)), [{"OBJECTID": 1}])

            not_record = Path(directory) / "not-record.jsonl"
            not_record.write_text("[1]\n", encoding="utf-8")
            with self.assertRaises(FoodSafetyError):
                read_records(str(not_record))

    def test_diff_records_reports_changes_and_errors(self) -> None:
        diff = diff_records(
            [{"OBJECTID": 1, "Name": "Old"}, {"OBJECTID": 2, "Name": "Removed"}],
            [{"OBJECTID": 1, "Name": "New"}, {"OBJECTID": 3, "Name": "Added"}],
        )

        self.assertEqual(
            [record["change"] for record in diff], ["removed", "added", "changed"]
        )
        self.assertEqual(
            compact_diff_record(diff[-1]),
            {"change": "changed", "key": "1", "changed_fields": "Name"},
        )
        self.assertEqual(
            default_key_field([{"business_record_id": "PFE-1"}]), "business_record_id"
        )

        with self.assertRaises(FoodSafetyError):
            diff_records([], [])
        with self.assertRaises(FoodSafetyError):
            diff_records([{"OBJECTID": 1}], [{"Name": "missing"}], key_field="OBJECTID")
        with self.assertRaises(FoodSafetyError):
            diff_records([{"OBJECTID": 1}, {"OBJECTID": 1}], [], key_field="OBJECTID")

    def _records(self) -> list[dict]:
        return payload_records(
            {
                "features": [
                    {"attributes": {"OBJECTID": 1, "Business_Name": "Alpha"}},
                    {"attributes": {"OBJECTID": 2, "Business_Name": "Beta, LLC"}},
                ]
            }
        )


if __name__ == "__main__":
    unittest.main()
