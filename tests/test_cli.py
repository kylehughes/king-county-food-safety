from __future__ import annotations

import contextlib
from datetime import date
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from king_county_food_safety import cli
from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.models import (
    FacilityRecord,
    Feature,
    FieldInfo,
    FoodSafetyLayer,
    GeocodeCandidate,
    Geometry,
    InspectionRecord,
    InspectionWithViolations,
    LayerInfo,
    RatingSummary,
    ViolationRecord,
)


class FakeRawClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "fields": [{"name": "OBJECTID"}, {"name": "Name"}],
            "features": [{"attributes": {"OBJECTID": 1, "Name": "Alpha"}}],
        }
        self.calls: list[tuple[str, object]] = []

    def query_payload(self, query: object) -> dict:
        self.calls.append(("query", query))
        return self.payload

    def query_all_payload(self, query: object, *, page_size: int = 2000, record_limit: int | None = None) -> dict:
        self.calls.append(("query_all", query, page_size, record_limit))
        return self.payload


class FakeAPI:
    def __init__(self, raw_payload: dict | None = None) -> None:
        self.client = FakeRawClient(raw_payload)
        self.calls: list[tuple[str, tuple, dict]] = []
        self.geocode_candidates = [_candidate()]

    def count(self, *args: object, **kwargs: object) -> int:
        self.calls.append(("count", args, kwargs))
        return 3

    def facilities_for_ids(self, *args: object, **kwargs: object) -> list[Feature[FacilityRecord]]:
        self.calls.append(("facilities_for_ids", args, kwargs))
        return [_facility("PFE-1"), _facility("PFE-2", object_id=2)]

    def facility(self, *args: object, **kwargs: object) -> Feature[FacilityRecord]:
        self.calls.append(("facility", args, kwargs))
        return _facility("PFE-1")

    def geocode(self, *args: object, **kwargs: object) -> list[GeocodeCandidate]:
        self.calls.append(("geocode", args, kwargs))
        return self.geocode_candidates

    def inspections(self, *args: object, **kwargs: object) -> list[Feature[InspectionRecord]]:
        self.calls.append(("inspections", args, kwargs))
        return [_inspection("PFE-1")]

    def inspections_for_facility_ids(self, *args: object, **kwargs: object) -> list[Feature[InspectionRecord]]:
        self.calls.append(("inspections_for_facility_ids", args, kwargs))
        return [_inspection("PFE-1"), _inspection("PFE-2", serial="S2")]

    def layer_info(self, *args: object, **kwargs: object) -> LayerInfo:
        self.calls.append(("layer_info", args, kwargs))
        return LayerInfo(
            display_field="Business_Name",
            fields=[FieldInfo(alias="OBJECTID", length=None, name="OBJECTID", type="esriFieldTypeOID")],
            geometry_type="esriGeometryPoint",
            global_id_field=None,
            max_record_count=2000,
            name="Facilities",
            object_id_field="OBJECTID",
        )

    def nearby_facilities(self, *args: object, **kwargs: object) -> list[Feature[FacilityRecord]]:
        self.calls.append(("nearby_facilities", args, kwargs))
        return [_facility("PFE-1", x=-122.3, y=47.6), _facility("PFE-2", object_id=2, x=-122.31, y=47.61)]

    def rating_summary(self, *args: object, **kwargs: object) -> list[Feature[RatingSummary]]:
        self.calls.append(("rating_summary", args, kwargs))
        return [Feature(RatingSummary(count=2, rating="Good"))]

    def search_facilities(self, *args: object, **kwargs: object) -> list[Feature[FacilityRecord]]:
        self.calls.append(("search_facilities", args, kwargs))
        return [_facility("PFE-1")]

    def violations(self, *args: object, **kwargs: object) -> list[Feature[ViolationRecord]]:
        self.calls.append(("violations", args, kwargs))
        return [_violation("S1")]

    def violations_for_inspection_serial_numbers(self, *args: object, **kwargs: object) -> list[Feature[ViolationRecord]]:
        self.calls.append(("violations_for_inspection_serial_numbers", args, kwargs))
        return [_violation("S1"), _violation("S2")]


class FailingSearchAPI:
    def search_facilities(self, *args: object, **kwargs: object) -> object:
        raise FoodSafetyError("Network request failed for https://example.test/query")


class CLITests(unittest.TestCase):
    def test_root_network_options_configure_client(self) -> None:
        api = FakeAPI()
        with patch("king_county_food_safety.cli.FoodSafetyAPI", return_value=api) as api_factory:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--timeout", "1.5", "--retries", "2", "metadata"])

        client = api_factory.call_args.kwargs["client"]
        self.assertEqual(client.timeout, 1.5)
        self.assertEqual(client.retries, 2)

    def test_food_safety_errors_exit_with_concise_message(self) -> None:
        stderr = io.StringIO()

        with patch("king_county_food_safety.cli.FoodSafetyAPI", return_value=FailingSearchAPI()):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exit_error:
                    cli.main(["search", "pizza"])

        self.assertEqual(exit_error.exception.code, 1)
        self.assertEqual(stderr.getvalue(), "Network request failed for https://example.test/query\n")
        self.assertNotIn("Traceback", stderr.getvalue())

        with patch("king_county_food_safety.cli.FoodSafetyAPI", return_value=FailingSearchAPI()):
            with self.assertRaises(FoodSafetyError):
                cli.main(["--verbose", "search", "pizza"])

    def test_count_search_facility_and_geocode_commands(self) -> None:
        api = FakeAPI()

        self.assertEqual(_run(["count", "facilities"], api).stdout, "3\n")
        self.assertEqual(json.loads(_run(["count", "facilities", "--json"], api).stdout)[0]["count"], 3)
        search = _run(
            [
                "search",
                "pizza",
                "--city",
                "Seattle",
                "--zip",
                "98105",
                "--rating",
                "good",
                "--status",
                "Active",
                "--establishment-type",
                "Risk",
                "--updated-since",
                "2026-01-01",
                "--json",
            ],
            api,
        )
        self.assertEqual(json.loads(search.stdout)[0]["business_record_id"], "PFE-1")
        self.assertEqual(api.calls[-1][2]["updated_since"], date(2026, 1, 1))

        facility = _run(["facility", "PFE-1", "--with-inspections", "--with-violations", "--json"], api)
        self.assertEqual(json.loads(facility.stdout)[0]["business_name"], "Alpha")
        table_facility = _run(["facility", "PFE-1", "--with-inspections"], api)
        self.assertIn("Business Record ID", table_facility.stdout)

        geocode = _run(["geocode", "111 NE 45TH ST", "--city", "Seattle", "--jsonl"], api)
        self.assertEqual(json.loads(geocode.stdout)["score"], 100)

    def test_facility_and_inspection_watchlist_files(self) -> None:
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ids.txt"
            path.write_text("PFE-1\nPFE-2\n", encoding="utf-8")

            facilities = _run(["facility", "--input-file", str(path), "--jsonl"], api)
            self.assertEqual(len(facilities.stdout.splitlines()), 2)

            inspections = _run(
                [
                    "inspections",
                    "--input-file",
                    str(path),
                    "--date-from",
                    "2025-01-01",
                    "--date-to",
                    "2025-12-31",
                    "--result",
                    "Satisfactory",
                    "--score-min",
                    "0",
                    "--score-max",
                    "10",
                    "--updated-since",
                    "2026-01-01",
                    "--with-violations",
                    "--jsonl",
                ],
                api,
            )
            self.assertGreaterEqual(len(inspections.stdout.splitlines()), 2)
            self.assertEqual(api.calls[-2][0], "inspections_for_facility_ids")

            single = _run(["inspections", "PFE-1", "--json"], api)
            self.assertEqual(json.loads(single.stdout)[0]["inspection_serial_number"], "S1")

            stdin = io.StringIO("PFE-1\nPFE-2\n")
            with patch("sys.stdin", stdin):
                streamed = _run(["inspections", "--stdin", "--jsonl"], api)
            self.assertEqual(len(streamed.stdout.splitlines()), 2)

    def test_violations_metadata_ratings_near_and_errors(self) -> None:
        api = FakeAPI()

        violations = _run(
            [
                "violations",
                "S1",
                "--description",
                "hands",
                "--points-min",
                "1",
                "--points-max",
                "10",
                "--type",
                "red",
                "--json",
            ],
            api,
        )
        self.assertEqual(json.loads(violations.stdout)[0]["violation_type"], "RED")

        metadata = _run(["metadata", "facilities", "--json"], api)
        self.assertEqual(json.loads(metadata.stdout)[0]["name"], "OBJECTID")

        layers = _run(["metadata", "--jsonl"], api)
        self.assertEqual(len(layers.stdout.splitlines()), 4)

        ratings = _run(["ratings", "--include-inactive", "--json"], api)
        self.assertEqual(json.loads(ratings.stdout)[0]["rating"], "Good")

        near = _run(["near", "--lat", "47.6", "--lon", "-122.3", "--radius", "1", "--limit", "1", "--json"], api)
        self.assertEqual(len(json.loads(near.stdout)), 1)
        near_address = _run(["near", "111 NE 45TH ST", "--city", "Seattle", "--json"], api)
        self.assertGreaterEqual(len(json.loads(near_address.stdout)), 1)

        with self.assertRaises(SystemExit):
            _run(["near", "--lat", "47.6"], api)
        api.geocode_candidates = []
        with self.assertRaises(SystemExit):
            _run(["near", "missing"], api)
        with self.assertRaises(SystemExit):
            _run(["inspections", "PFE-1", "--score-min", "10", "--score-max", "1"], api)
        with self.assertRaises(SystemExit):
            _run(["violations", "S1", "--points-min", "10", "--points-max", "1"], api)
        with self.assertRaises(SystemExit):
            _run(["facility", "--input-file", _temp_ids(), "--with-inspections"], api)
        with self.assertRaises(SystemExit):
            _run(["geocode"], api)
        with self.assertRaises(SystemExit):
            _run(["search", "--updated-since", "bad-date"], api)
        with self.assertRaises(SystemExit):
            _run(["search", "--fields", ","], api)
        with self.assertRaises(SystemExit):
            _run(["search", "--limit", "0"], api)
        with self.assertRaises(SystemExit):
            _run(["violations"], api)

    def test_query_export_snapshot_and_diff_commands(self) -> None:
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            query = _run(
                [
                    "query",
                    "facilities",
                    "--all",
                    "--jsonl",
                    "--limit",
                    "1",
                    "--page-size",
                    "1",
                    "--resume-offset",
                    "2",
                    "--out-fields",
                    "OBJECTID,Name",
                    "--manifest",
                    str(manifest),
                ],
                api,
            )
            self.assertEqual(json.loads(query.stdout), {"Name": "Alpha", "OBJECTID": 1})
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["command"], "query")

            raw = _run(["query", "facilities"], api)
            self.assertIn('"features"', raw.stdout)
            spatial = _run(["query", "facilities", "--lat", "47.6", "--lon", "-122.3", "--jsonl"], api)
            self.assertEqual(json.loads(spatial.stdout)["OBJECTID"], 1)

            aggregate = _run(
                [
                    "export",
                    "facilities",
                    "--csv",
                    "--fields",
                    "OBJECTID,Name",
                    "--group-by",
                    "Name",
                    "--stat",
                    "count:OBJECTID:count",
                ],
                api,
            )
            self.assertEqual(aggregate.stdout, "OBJECTID,Name\n1,Alpha\n")

            large_export_api = FakeAPI()
            large_export = _run(["export", "facilities", "--jsonl", "--limit", "5000"], large_export_api)
            self.assertEqual(json.loads(large_export.stdout), {"Name": "Alpha", "OBJECTID": 1})
            self.assertEqual(large_export_api.client.calls[-1][3], 5000)

            empty_export_api = FakeAPI(
                raw_payload={
                    "fields": ["ignored", {"name": None}, {"name": "OBJECTID"}, {"name": "Name"}],
                    "features": [],
                }
            )
            empty_export = _run(
                [
                    "export",
                    "facilities",
                    "--csv",
                    "--fields",
                    "OBJECTID,Name",
                ],
                empty_export_api,
            )
            self.assertEqual(empty_export.stdout, "OBJECTID,Name\n")
            self.assertEqual(
                cli._record_fields([{"dynamic": "value"}], {"fields": [{"name": "OBJECTID"}]}),
                ["OBJECTID", "dynamic"],
            )

            snapshot_path = Path(directory) / "snapshot.jsonl"
            _run(["snapshot", "facilities", "--output", str(snapshot_path)], api)
            self.assertTrue(snapshot_path.exists())
            self.assertTrue(Path(f"{snapshot_path}.manifest.json").exists())
            stdout_snapshot = _run(["snapshot", "facilities", "--output", "-"], api)
            self.assertEqual(json.loads(stdout_snapshot.stdout)["OBJECTID"], 1)

            large_snapshot_api = FakeAPI()
            _run(["snapshot", "facilities", "--output", "-", "--limit", "5000"], large_snapshot_api)
            self.assertEqual(large_snapshot_api.client.calls[-1][3], 5000)

            old_snapshot = Path(directory) / "old.jsonl"
            new_snapshot = Path(directory) / "new.jsonl"
            old_snapshot.write_text('{"OBJECTID": 1, "Name": "Alpha"}\n{"OBJECTID": 2, "Name": "Beta"}\n', encoding="utf-8")
            new_snapshot.write_text('{"OBJECTID": 1, "Name": "Alpha Prime"}\n{"OBJECTID": 3, "Name": "Gamma"}\n', encoding="utf-8")
            diff = _run(["diff", str(old_snapshot), str(new_snapshot), "--json"], api)
            changes = {record["change"] for record in json.loads(diff.stdout)}
            self.assertEqual(changes, {"added", "changed", "removed"})

            compact = _run(["diff", str(old_snapshot), str(new_snapshot), "--csv"], api)
            self.assertIn("change,key,changed_fields", compact.stdout)

    def test_query_validation_errors(self) -> None:
        api = FakeAPI()
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--count", "--ids"], api)
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--group-by", "Name"], api)
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--group-by", ","], api)
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--stat", "bad"], api)
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--offset", "1", "--resume-offset", "2"], api)
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--lat", "47.6"], api)
        with self.assertRaises(SystemExit):
            _run(["query", "facilities", "--limit", "5000"], api)
        query_all_api = FakeAPI()
        _run(["query", "facilities", "--all", "--jsonl", "--limit", "5000"], query_all_api)
        self.assertEqual(query_all_api.client.calls[-1][3], 5000)
        with self.assertRaises(SystemExit):
            _run(["export", "facilities", "--limit", "0"], api)
        with self.assertRaises(SystemExit):
            _run(["--timeout", "0", "metadata"], api)
        with self.assertRaises(SystemExit):
            _run(["--retries", "-1", "metadata"], api)

    def test_module_entry_points_run(self) -> None:
        api = FakeAPI()
        project_root = Path(__file__).resolve().parents[1]
        stdout = io.StringIO()
        with patch("king_county_food_safety.cli.FoodSafetyAPI", return_value=api):
            with patch("sys.argv", ["king-county-food-safety", "metadata"]):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(SystemExit) as exit_error:
                        runpy.run_path(str(project_root / "src/king_county_food_safety/__main__.py"), run_name="__main__")
        self.assertEqual(exit_error.exception.code, 0)
        self.assertIn("facilities", stdout.getvalue())

        stdout = io.StringIO()
        with patch("king_county_food_safety.cli.FoodSafetyAPI", return_value=api):
            with patch("sys.argv", ["king-county-food-safety", "metadata"]):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(SystemExit) as exit_error:
                        runpy.run_path(str(project_root / "src/king_county_food_safety/cli.py"), run_name="__main__")
        self.assertEqual(exit_error.exception.code, 0)


class CommandResult:
    def __init__(self, stdout: str, stderr: str) -> None:
        self.stdout = stdout
        self.stderr = stderr


def _run(args: list[str], api: FakeAPI) -> CommandResult:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("king_county_food_safety.cli.FoodSafetyAPI", return_value=api):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            cli.main(args)
    return CommandResult(stdout.getvalue(), stderr.getvalue())


def _temp_ids() -> str:
    temporary = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
    with temporary:
        temporary.write("PFE-1\nPFE-2\n")
    return temporary.name


def _candidate() -> GeocodeCandidate:
    return GeocodeCandidate(
        address="111 NE 45TH ST",
        attributes=None,
        location=Geometry(x=-122.3, y=47.6),
        score=100,
    )


def _facility(business_record_id: str, *, object_id: int = 1, x: float = -122.3, y: float = 47.6) -> Feature[FacilityRecord]:
    return Feature(
        FacilityRecord(
            business_address="111 NE 45TH ST",
            business_city="SEATTLE",
            business_establishment_description="Seating 0-12 - Risk Category III",
            business_grade="Good",
            business_latitude=None,
            business_longitude=None,
            business_name="Alpha",
            business_phone=None,
            business_program_identifier="",
            business_record_id=business_record_id,
            business_status="Active",
            business_zip="98105",
            load_date_milliseconds=1781420580000,
            object_id=object_id,
            parcel_latitude=None,
            parcel_longitude=None,
            parcel_number=None,
        ),
        Geometry(x=x, y=y),
    )


def _inspection(business_record_id: str, *, serial: str = "S1") -> Feature[InspectionRecord]:
    return Feature(
        InspectionRecord(
            business_record_id=business_record_id,
            inspection_business_name="Alpha",
            inspection_date="2025-01-01",
            inspection_result="Satisfactory",
            inspection_score=0,
            inspection_serial_number=serial,
            inspection_type="Routine Inspection/Field Review",
            load_date_milliseconds=1781420580000,
            object_id=1,
        )
    )


def _violation(serial: str) -> Feature[ViolationRecord]:
    return Feature(
        ViolationRecord(
            inspection_serial_number=serial,
            load_date_milliseconds=1781420580000,
            object_id=1,
            violation_description="0600 Adequate handwashing facilities",
            violation_points=10,
            violation_type="RED",
        )
    )


if __name__ == "__main__":
    unittest.main()
