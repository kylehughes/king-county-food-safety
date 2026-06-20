import json
import unittest

from king_county_food_safety.models import (
    FacilityRecord,
    FieldInfo,
    FoodSafetyLayer,
    FoodSafetyRating,
    GeocodeCandidate,
    Geometry,
    InspectionRecord,
    LayerInfo,
    RatingSummary,
    ViolationRecord,
    geometry_from_arcgis,
    miles_between,
)
from king_county_food_safety.errors import FoodSafetyError


class ModelTests(unittest.TestCase):
    def test_distance_for_nearby_coordinates(self) -> None:
        first = Geometry(x=-122.327789, y=47.661115)
        second = Geometry(x=-122.323801, y=47.661199)
        distance = miles_between(first, second)
        self.assertGreater(distance, 0.18)
        self.assertLess(distance, 0.20)

    def test_facility_decodes_arcgis_fields(self) -> None:
        record = FacilityRecord.from_arcgis(
            {
                "OBJECTID": 2072,
                "Business_Record_ID": "PFE-PR-3126839",
                "Business_Name": "DICK'S DRIVE IN",
                "Business_Program_Identifier": "",
                "Business_Establishment_Descr": "Seating 0-12 - Risk Category III",
                "Business_Address": "111 NE 45TH ST",
                "Business_City": "SEATTLE",
                "Business_Phone": None,
                "Businesss_Location_Long": None,
                "Business_Location_Lat": None,
                "Business_Location_Zip": "98105",
                "Load_DT_TM": 1781420580000,
                "Business_Grade": "Excellent",
                "Parcel_Number": "3131200340",
                "Parcel_Lat": None,
                "Parcel_Lon": None,
                "Business_Status": "Active",
            }
        )

        self.assertEqual(record.object_id, 2072)
        self.assertEqual(record.business_record_id, "PFE-PR-3126839")
        self.assertEqual(record.display_rating, "Excellent")
        self.assertEqual(record.city_state_zip, "SEATTLE, WA 98105")

    def test_facility_city_state_zip_handles_missing_parts_and_numeric_values(
        self,
    ) -> None:
        payload = {
            "OBJECTID": 1,
            "Business_Record_ID": "PFE-1",
            "Business_Name": "Alpha",
            "Business_Program_Identifier": "",
            "Business_Establishment_Descr": "",
            "Business_Address": None,
            "Business_City": None,
            "Business_Phone": None,
            "Businesss_Location_Long": "-122.3",
            "Business_Location_Lat": "47.6",
            "Business_Location_Zip": "",
            "Load_DT_TM": "",
            "Business_Grade": "",
            "Parcel_Number": None,
            "Parcel_Lat": "47.61",
            "Parcel_Lon": "-122.31",
            "Business_Status": "Inactive",
        }
        record = FacilityRecord.from_arcgis(payload)
        self.assertEqual(record.city_state_zip, "-")
        self.assertEqual(record.display_rating, "Rating not available")
        self.assertEqual(record.business_latitude, 47.6)
        self.assertEqual(record.parcel_longitude, -122.31)

        payload["Business_City"] = "SEATTLE"
        self.assertEqual(FacilityRecord.from_arcgis(payload).city_state_zip, "SEATTLE")

        payload["Business_City"] = None
        payload["Business_Location_Zip"] = "98105"
        self.assertEqual(FacilityRecord.from_arcgis(payload).city_state_zip, "98105")

    def test_geocoder_candidate_decodes_coordinates(self) -> None:
        payload = json.loads(
            """
            {
              "address": "111 NE 45TH ST, Seattle, 98105",
              "location": {"x": -122.32778921667466, "y": 47.661114833276166},
              "score": 100,
              "attributes": {
                "Match_addr": "111 NE 45TH ST, Seattle, 98105",
                "City": "Seattle",
                "ZIP": "98105",
                "Addr_type": "PointAddress"
              }
            }
            """
        )

        candidate = GeocodeCandidate.from_arcgis(payload)
        self.assertEqual(candidate.score, 100)
        self.assertEqual(candidate.location.y, 47.661114833276166)
        self.assertIsNotNone(candidate.attributes)
        self.assertEqual(candidate.attributes.address_type, "PointAddress")

    def test_inspection_and_violation_decode_arcgis_fields(self) -> None:
        inspection = InspectionRecord.from_arcgis(
            {
                "OBJECTID": 7191,
                "Inspection_Serial_Num": "PFE-DABP9LQSH",
                "Business_Record_ID": "PFE-PR-3126839",
                "Inspection_Business_Name": "DICK'S DRIVE IN",
                "Inspection_Type": "Routine Inspection/Field Review",
                "Inspection_Date": "2024-04-18",
                "Inspection_Score": 10,
                "Inspection_Result": "Unsatisfactory",
                "Load_DT_TM": 1781420580000,
            }
        )
        violation = ViolationRecord.from_arcgis(
            {
                "OBJECTID": 54641,
                "Inspection_Serial_Num": "PFE-DABP9LQSH",
                "Violation_Type": "RED",
                "Violation_Descr": "0600 Adequate handwashing facilities",
                "Violation_Points": 10,
                "Load_DT_TM": 1781420580000,
            }
        )

        self.assertEqual(inspection.inspection_date, "2024-04-18")
        self.assertEqual(inspection.inspection_score, 10)
        self.assertEqual(violation.violation_type, "RED")
        self.assertEqual(violation.violation_points, 10)

    def test_rating_aliases_resolve(self) -> None:
        self.assertIs(
            FoodSafetyRating.from_cli("excellent"), FoodSafetyRating.EXCELLENT
        )
        self.assertIs(
            FoodSafetyRating.from_cli("needs improvement"),
            FoodSafetyRating.NEEDS_TO_IMPROVE,
        )
        self.assertIs(
            FoodSafetyRating.from_cli("not-available"), FoodSafetyRating.NOT_AVAILABLE
        )
        self.assertIs(FoodSafetyRating.from_cli("ok"), FoodSafetyRating.OKAY)

    def test_layer_and_rating_errors_and_properties(self) -> None:
        self.assertIs(
            FoodSafetyLayer.from_cli("restaurants"), FoodSafetyLayer.FACILITIES
        )
        self.assertEqual(FoodSafetyLayer.INSPECTIONS.display_name, "Inspections")
        self.assertIn("/1", FoodSafetyLayer.INSPECTIONS.url)
        self.assertEqual(FoodSafetyLayer.SEARCH.display_name, "Search view")
        self.assertIn("SEARCH_view", FoodSafetyLayer.SEARCH.url)
        self.assertEqual(FoodSafetyLayer.VIOLATIONS.display_name, "Violations")
        self.assertIn("/2", FoodSafetyLayer.VIOLATIONS.url)
        with self.assertRaises(FoodSafetyError):
            FoodSafetyLayer.from_cli("unknown")

        self.assertEqual(
            FoodSafetyRating.NOT_AVAILABLE.display_name, "Rating not available"
        )
        self.assertIn(
            "Business_Grade IS NULL", FoodSafetyRating.NOT_AVAILABLE.where_clause
        )
        with self.assertRaises(FoodSafetyError):
            FoodSafetyRating.from_cli("bad")

    def test_metadata_rating_summary_and_geometry_helpers(self) -> None:
        summary = RatingSummary.from_arcgis({"count": 4, "Business_Grade": None})
        self.assertEqual(summary.display_rating, "Rating not available")
        self.assertEqual(summary.count, 4)

        field = FieldInfo.from_arcgis(
            {"name": "Business_Name", "type": "esriFieldTypeString", "length": "100"}
        )
        self.assertEqual(field.length, 100)

        info = LayerInfo.from_arcgis(
            {
                "displayField": "Business_Name",
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                "geometryType": "esriGeometryPoint",
                "globalIdField": "GlobalID",
                "maxRecordCount": "2000",
                "name": "Facilities",
                "objectIdField": "OBJECTID",
            }
        )
        self.assertEqual(info.max_record_count, 2000)
        self.assertEqual(info.fields[0].name, "OBJECTID")

        self.assertIsNone(geometry_from_arcgis(None))
        self.assertEqual(
            geometry_from_arcgis({"x": "-122.3", "y": "47.6"}),
            Geometry(x=-122.3, y=47.6),
        )


if __name__ == "__main__":
    unittest.main()
