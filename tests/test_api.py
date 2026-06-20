from __future__ import annotations

from datetime import date
import unittest

from king_county_food_safety.api import FoodSafetyAPI, MAX_PAGE_SIZE
from king_county_food_safety.arcgis import FeatureQuery
from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.models import (
    FacilityRecord,
    Feature,
    FieldInfo,
    FoodSafetyLayer,
    FoodSafetyRating,
    Geometry,
    GeocodeCandidate,
    InspectionRecord,
    LayerInfo,
    RatingSummary,
    ViolationRecord,
)


class FakeClient:
    def __init__(self) -> None:
        self.count_queries: list[FeatureQuery] = []
        self.geocode_calls: list[tuple[str, str | None, str | None, int]] = []
        self.layer_info_calls: list[FoodSafetyLayer] = []
        self.queries: list[tuple[FeatureQuery, type]] = []
        self.query_all_calls: list[tuple[FeatureQuery, type, int]] = []
        self.next_count = 7
        self.next_geocode = [
            GeocodeCandidate(
                address="111 NE 45TH ST",
                attributes=None,
                location=Geometry(x=-122.3, y=47.6),
                score=100,
            )
        ]
        self.next_layer_info = LayerInfo(
            display_field=None,
            fields=[
                FieldInfo(
                    alias="OBJECTID",
                    length=None,
                    name="OBJECTID",
                    type="esriFieldTypeOID",
                )
            ],
            geometry_type="esriGeometryPoint",
            global_id_field=None,
            max_record_count=2000,
            name="Facilities",
            object_id_field="OBJECTID",
        )
        self.query_results: list[list] = []
        self.query_all_results: list[list] = []

    def count(self, query: FeatureQuery) -> int:
        self.count_queries.append(query)
        return self.next_count

    def geocode(
        self,
        address: str,
        *,
        city: str | None = None,
        zip_code: str | None = None,
        limit: int = 5,
    ) -> list[GeocodeCandidate]:
        self.geocode_calls.append((address, city, zip_code, limit))
        return self.next_geocode

    def layer_info(self, layer: FoodSafetyLayer) -> LayerInfo:
        self.layer_info_calls.append(layer)
        return self.next_layer_info

    def query(self, query: FeatureQuery, record_type: type) -> list:
        self.queries.append((query, record_type))
        return self.query_results.pop(0) if self.query_results else []

    def query_all(
        self, query: FeatureQuery, record_type: type, *, page_size: int = 2000
    ) -> list:
        self.query_all_calls.append((query, record_type, page_size))
        return self.query_all_results.pop(0) if self.query_all_results else []


class FoodSafetyAPITests(unittest.TestCase):
    def test_count_builds_count_query(self) -> None:
        client = FakeClient()
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        count = api.count(FoodSafetyLayer.FACILITIES, "Business_Status = 'Active'")

        self.assertEqual(count, 7)
        query = client.count_queries[0]
        self.assertIs(query.layer, FoodSafetyLayer.FACILITIES)
        self.assertEqual(query.where_clause, "Business_Status = 'Active'")
        self.assertTrue(query.return_count_only)

    def test_facility_returns_first_match_and_errors_when_missing(self) -> None:
        facility = _facility("PFE-1")
        client = FakeClient()
        client.query_results.append([facility])
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        self.assertIs(api.facility("PFE-1"), facility)
        query = client.queries[0][0]
        self.assertIn("Business_Record_ID = 'PFE-1'", query.where_clause)
        self.assertIn("Business_Status = 'Active'", query.where_clause)

        with self.assertRaises(FoodSafetyError):
            api.facility("missing")

    def test_facilities_for_ids_batches_business_and_object_ids(self) -> None:
        client = FakeClient()
        client.query_all_results.extend(
            [[_facility("PFE-1")], [_facility("PFE-2", object_id=2)]]
        )
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        facilities = api.facilities_for_ids(["PFE-1", "2", "PFE-1"])

        self.assertEqual(
            [item.attributes.business_record_id for item in facilities],
            ["PFE-1", "PFE-2"],
        )
        business_query, _, page_size = client.query_all_calls[0]
        object_query, _, _ = client.query_all_calls[1]
        self.assertEqual(page_size, MAX_PAGE_SIZE)
        self.assertIn("Business_Record_ID IN ('PFE-1')", business_query.where_clause)
        self.assertIn("OBJECTID IN (2)", object_query.where_clause)

    def test_geocode_and_layer_info_delegate_to_client(self) -> None:
        client = FakeClient()
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        self.assertEqual(
            api.geocode("111 NE 45TH ST", city="Seattle", zip_code="98105", limit=1),
            client.next_geocode,
        )
        self.assertEqual(
            api.layer_info(FoodSafetyLayer.FACILITIES), client.next_layer_info
        )
        self.assertEqual(
            client.geocode_calls, [("111 NE 45TH ST", "Seattle", "98105", 1)]
        )
        self.assertEqual(client.layer_info_calls, [FoodSafetyLayer.FACILITIES])

    def test_inspections_resolve_facility_and_apply_filters(self) -> None:
        client = FakeClient()
        client.query_results.extend(
            [[_facility("PFE-1")], [_inspection("PFE-1", score=12)]]
        )
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        inspections = api.inspections(
            "PFE-1",
            date_from=date(2025, 1, 1),
            date_to=date(2025, 12, 31),
            result="Unsatisfactory",
            score_min=10,
            score_max=20,
            updated_since=date(2026, 1, 1),
        )

        self.assertEqual(inspections[0].attributes.inspection_score, 12)
        query = client.queries[1][0]
        self.assertIn("Inspection_Date >= DATE '2025-01-01'", query.where_clause)
        self.assertIn("Inspection_Date <= DATE '2025-12-31'", query.where_clause)
        self.assertIn("Inspection_Result = 'Unsatisfactory'", query.where_clause)
        self.assertIn("Inspection_Score >= 10", query.where_clause)
        self.assertIn("Inspection_Score <= 20", query.where_clause)
        self.assertIn(
            "Load_DT_TM >= TIMESTAMP '2026-01-01 00:00:00'", query.where_clause
        )

    def test_inspections_error_when_facility_has_no_business_record_id(self) -> None:
        client = FakeClient()
        client.query_results.append([_facility(None)])
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        with self.assertRaises(FoodSafetyError):
            api.inspections("1")

    def test_inspections_for_facility_ids_resolves_object_ids_and_limits_per_facility(
        self,
    ) -> None:
        client = FakeClient()
        client.query_results.append([_facility("PFE-1")])
        client.query_all_results.append(
            [
                _inspection("PFE-2", "2025-01-02", object_id=2),
                _inspection("PFE-2", "2025-01-01", object_id=1),
                _inspection("PFE-1", "2025-01-03", object_id=3),
                _inspection("PFE-1", "2025-01-02", object_id=2),
            ]
        )
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        inspections = api.inspections_for_facility_ids(
            ["PFE-2", "1"], limit_per_facility=1, include_non_public=True
        )

        self.assertEqual(len(inspections), 2)
        self.assertEqual(
            client.queries[0][0].fields,
            ("Business_Record_ID", "OBJECTID", "Business_Status"),
        )
        inspection_query = client.query_all_calls[0][0]
        self.assertIn(
            "Business_Record_ID IN ('PFE-2','PFE-1')", inspection_query.where_clause
        )
        self.assertNotIn("Consultation/Education", inspection_query.where_clause)

    def test_inspections_for_facility_ids_without_limit_returns_all(self) -> None:
        client = FakeClient()
        client.query_all_results.append(
            [_inspection("PFE-1"), _inspection("PFE-1", object_id=2)]
        )
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        inspections = api.inspections_for_facility_ids(
            ["PFE-1"], limit_per_facility=None
        )

        self.assertEqual(len(inspections), 2)

    def test_nearby_search_and_rating_summary_build_queries(self) -> None:
        client = FakeClient()
        client.query_results.extend(
            [[_facility("PFE-1")], [Feature(RatingSummary(count=2, rating="Good"))]]
        )
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        api.nearby_facilities(
            latitude=47.6,
            longitude=-122.3,
            radius_miles=0.25,
            rating=FoodSafetyRating.GOOD,
            establishment_type="Risk Category III",
            status="Active",
            updated_since=date(2026, 1, 1),
        )
        api.rating_summary(include_inactive=True)

        nearby_query = client.queries[0][0]
        self.assertIsNotNone(nearby_query.spatial_filter)
        self.assertIn("Business_Grade = 'Good'", nearby_query.where_clause)
        self.assertIn("Business_Status = 'Active'", nearby_query.where_clause)
        self.assertIn("Business_Establishment_Descr", nearby_query.where_clause)
        summary_query = client.queries[1][0]
        self.assertEqual(summary_query.where_clause, "1=1")
        self.assertEqual(
            summary_query.group_by_fields_for_statistics, ("Business_Grade",)
        )

    def test_search_facilities_applies_facility_filters(self) -> None:
        client = FakeClient()
        client.query_results.append([_facility("PFE-1")])
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        api.search_facilities(
            "pizza",
            city="Seattle",
            zip_code="98105",
            rating=FoodSafetyRating.NOT_AVAILABLE,
            include_inactive=True,
            establishment_type="Seating",
            status="Inactive",
            updated_since=date(2026, 1, 1),
            limit=5,
            offset=10,
        )

        query = client.queries[0][0]
        self.assertEqual(query.limit, 5)
        self.assertEqual(query.offset, 10)
        self.assertIn("Business_Status = 'Inactive'", query.where_clause)
        self.assertIn("UPPER(Business_Name) LIKE '%PIZZA%'", query.where_clause)
        self.assertIn("Business_Location_Zip = '98105'", query.where_clause)
        self.assertIn("Business_Grade IS NULL", query.where_clause)

    def test_search_facilities_can_include_inactive_without_status_or_text(
        self,
    ) -> None:
        client = FakeClient()
        client.query_results.append([_facility("PFE-1")])
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        api.search_facilities(None, include_inactive=True)

        self.assertEqual(client.queries[0][0].where_clause, "1=1")

        client.query_results.append([_facility("PFE-2")])
        api.search_facilities(None)
        self.assertEqual(
            client.queries[1][0].where_clause, "(Business_Status = 'Active')"
        )

    def test_violations_apply_filters_for_single_and_batch(self) -> None:
        client = FakeClient()
        client.query_results.append([_violation("S1", points=10)])
        client.query_all_results.append([_violation("S2", points=5)])
        api = FoodSafetyAPI(client=client)  # type: ignore[arg-type]

        api.violations(
            "S1", description="hands", points_min=5, points_max=10, violation_type="red"
        )
        api.violations_for_inspection_serial_numbers(["S2"], violation_type="blue")

        single_query = client.queries[0][0]
        batch_query = client.query_all_calls[0][0]
        self.assertIn("Inspection_Serial_Num = 'S1'", single_query.where_clause)
        self.assertIn(
            "UPPER(Violation_Descr) LIKE '%HANDS%'", single_query.where_clause
        )
        self.assertIn("Violation_Points >= 5", single_query.where_clause)
        self.assertIn("Violation_Type = 'RED'", single_query.where_clause)
        self.assertIn("Inspection_Serial_Num IN ('S2')", batch_query.where_clause)
        self.assertIn("Violation_Type = 'BLUE'", batch_query.where_clause)

    def test_unique_non_empty_preserves_order(self) -> None:
        self.assertEqual(
            FoodSafetyAPI._unique_non_empty([" A ", "", "B", "A", "C"]), ["A", "B", "C"]
        )

    def test_chunks_split_values(self) -> None:
        self.assertEqual(
            FoodSafetyAPI._chunks(["A", "B", "C", "D", "E"], 2),
            [["A", "B"], ["C", "D"], ["E"]],
        )


def _facility(
    business_record_id: str | None, object_id: int = 1
) -> Feature[FacilityRecord]:
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
        Geometry(x=-122.3, y=47.6),
    )


def _inspection(
    business_record_id: str,
    inspection_date: str = "2025-01-01",
    *,
    object_id: int = 1,
    score: int = 0,
) -> Feature[InspectionRecord]:
    return Feature(
        InspectionRecord(
            business_record_id=business_record_id,
            inspection_business_name="Alpha",
            inspection_date=inspection_date,
            inspection_result="Satisfactory",
            inspection_score=score,
            inspection_serial_number=f"S{object_id}",
            inspection_type="Routine Inspection/Field Review",
            load_date_milliseconds=1781420580000,
            object_id=object_id,
        )
    )


def _violation(serial: str, *, points: int) -> Feature[ViolationRecord]:
    return Feature(
        ViolationRecord(
            inspection_serial_number=serial,
            load_date_milliseconds=1781420580000,
            object_id=1,
            violation_description="0600 Adequate handwashing facilities",
            violation_points=points,
            violation_type="RED",
        )
    )


if __name__ == "__main__":
    unittest.main()
