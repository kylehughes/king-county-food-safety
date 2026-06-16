import unittest
from urllib.parse import parse_qs, urlparse

from kc_food_safety.arcgis import FeatureQuery, SpatialFilter
from kc_food_safety.errors import FoodSafetyError
from kc_food_safety.models import FoodSafetyLayer


class FeatureQueryTests(unittest.TestCase):
    def test_invalid_limit_fails(self) -> None:
        with self.assertRaises(FoodSafetyError):
            FeatureQuery(layer=FoodSafetyLayer.FACILITIES, limit=0)

    def test_query_url_encodes_parameters(self) -> None:
        query = FeatureQuery(
            layer=FoodSafetyLayer.FACILITIES,
            where_clause="Business_Status = 'Active'",
            fields=("Business_Name", "Business_Grade"),
            return_geometry=True,
            order_by_fields=("Business_Name ASC",),
            limit=50,
            offset=10,
            spatial_filter=SpatialFilter(latitude=47.661115, longitude=-122.327789, radius_miles=0.25),
        )

        params = {key: values[0] for key, values in parse_qs(urlparse(query.url()).query).items()}
        self.assertEqual(params["where"], "Business_Status = 'Active'")
        self.assertEqual(params["outFields"], "Business_Name,Business_Grade")
        self.assertEqual(params["returnGeometry"], "true")
        self.assertEqual(params["orderByFields"], "Business_Name ASC")
        self.assertEqual(params["resultRecordCount"], "50")
        self.assertEqual(params["resultOffset"], "10")
        self.assertEqual(params["geometry"], "-122.327789,47.661115")
        self.assertEqual(params["distance"], "0.25")
        self.assertEqual(params["units"], "esriSRUnit_StatuteMile")


if __name__ == "__main__":
    unittest.main()
