import socket
from io import BytesIO
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from king_county_food_safety.arcgis import ArcGISClient, FeatureQuery
from king_county_food_safety.errors import ArcGISError, FoodSafetyError, HTTPStatusError, NetworkError
from king_county_food_safety.models import Feature, FoodSafetyLayer


class DummyRecord:
    def __init__(self, value: int) -> None:
        self.value = value


class PagingClient(ArcGISClient):
    def __init__(self, pages: list[list[Feature[DummyRecord]]]) -> None:
        super().__init__()
        self.calls: list[tuple[int | None, int | None]] = []
        self.pages = pages

    def query(self, query: FeatureQuery, record_type: type[DummyRecord]) -> list[Feature[DummyRecord]]:
        self.calls.append((query.limit, query.offset))
        return self.pages.pop(0)


class PayloadPagingClient(ArcGISClient):
    def __init__(self, pages: list[dict]) -> None:
        super().__init__()
        self.calls: list[tuple[int | None, int | None]] = []
        self.pages = pages

    def query_payload(self, query: FeatureQuery) -> dict:
        self.calls.append((query.limit, query.offset))
        return self.pages.pop(0)


class ArcGISClientTests(unittest.TestCase):
    def test_network_errors_are_wrapped_as_food_safety_error(self) -> None:
        url = "https://example.test/query"
        failures = [
            URLError("timed out"),
            TimeoutError("timed out"),
            socket.gaierror(8, "nodename nor servname provided"),
        ]

        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                with patch("king_county_food_safety.arcgis.urlopen", side_effect=failure):
                    with self.assertRaises(NetworkError) as error:
                        ArcGISClient(timeout=0.1).get_bytes(url)

                self.assertIs(error.exception.__cause__, failure)
                self.assertIn(url, str(error.exception))
                self.assertNotIn("\n", str(error.exception))
                self.assertNotIn("Traceback", str(error.exception))

    def test_get_bytes_reads_success_response_and_wraps_http_errors(self) -> None:
        response = Mock()
        response.status = 200
        response.read.return_value = b"{}"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)

        with patch("king_county_food_safety.arcgis.urlopen", return_value=response):
            self.assertEqual(ArcGISClient().get_bytes("https://example.test/query"), b"{}")

        bad_status = Mock()
        bad_status.status = 503
        bad_status.__enter__ = Mock(return_value=bad_status)
        bad_status.__exit__ = Mock(return_value=None)
        with patch("king_county_food_safety.arcgis.urlopen", return_value=bad_status):
            with self.assertRaises(HTTPStatusError):
                ArcGISClient().get_bytes("https://example.test/query")

        http_error = HTTPError("https://example.test/query", 500, "Server Error", {}, BytesIO(b""))
        with patch("king_county_food_safety.arcgis.urlopen", side_effect=http_error):
            with self.assertRaises(HTTPStatusError) as error:
                ArcGISClient().get_bytes("https://example.test/query")
        http_error.close()
        self.assertEqual(error.exception.status_code, 500)

    def test_get_bytes_retries_transient_network_errors(self) -> None:
        response = Mock()
        response.status = 200
        response.read.return_value = b"ok"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)

        with patch("king_county_food_safety.arcgis.urlopen", side_effect=[URLError("temporary"), response]) as urlopen:
            self.assertEqual(ArcGISClient(retries=1).get_bytes("https://example.test/query"), b"ok")
        self.assertEqual(urlopen.call_count, 2)

        with self.assertRaises(FoodSafetyError):
            ArcGISClient(retries=-1)
        with self.assertRaises(FoodSafetyError):
            ArcGISClient(timeout=0)

    def test_get_json_decodes_success_and_expected_error_shapes(self) -> None:
        client = ArcGISClient()

        with patch.object(client, "get_bytes", return_value=b'{"count": 3}'):
            self.assertEqual(client.get_json("https://example.test/query"), {"count": 3})
        with patch.object(client, "get_bytes", return_value=b"not-json"):
            with self.assertRaises(FoodSafetyError):
                client.get_json("https://example.test/query")
        with patch.object(client, "get_bytes", return_value=b'["not-object"]'):
            with self.assertRaises(FoodSafetyError):
                client.get_json("https://example.test/query")
        with patch.object(client, "get_bytes", return_value=b'{"error":{"code":400,"message":"Bad","details":["Nope"]}}'):
            with self.assertRaises(ArcGISError) as error:
                client.get_json("https://example.test/query")
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(error.exception.details, ["Nope"])

    def test_count_requires_count_field(self) -> None:
        client = ArcGISClient()
        with patch.object(client, "get_json", return_value={"count": "4"}):
            self.assertEqual(client.count(FeatureQuery(layer=FoodSafetyLayer.FACILITIES)), 4)
        with patch.object(client, "get_json", return_value={}):
            with self.assertRaises(FoodSafetyError):
                client.count(FeatureQuery(layer=FoodSafetyLayer.FACILITIES))

    def test_geocode_builds_single_line_and_structured_requests(self) -> None:
        client = ArcGISClient()
        payload = {
            "candidates": [
                {
                    "address": "111 NE 45TH ST",
                    "location": {"x": -122.3, "y": 47.6},
                    "score": 100,
                    "attributes": {"Addr_type": "PointAddress", "City": "Seattle", "Match_addr": "111 NE 45TH ST", "ZIP": "98105"},
                }
            ]
        }
        with patch.object(client, "get_json", return_value=payload) as get_json:
            candidates = client.geocode("111 NE 45TH ST")
            self.assertEqual(candidates[0].address, "111 NE 45TH ST")
            self.assertIn("SingleLine=111+NE+45TH+ST", get_json.call_args.args[0])

        with patch.object(client, "get_json", return_value={"candidates": []}) as get_json:
            self.assertEqual(client.geocode("111 NE 45TH ST", city="Seattle", zip_code="98105", limit=2), [])
            url = get_json.call_args.args[0]
            self.assertIn("Street=111+NE+45TH+ST", url)
            self.assertIn("City=Seattle", url)
            self.assertIn("ZIP=98105", url)

        with self.assertRaises(FoodSafetyError):
            client.geocode("111 NE 45TH ST", limit=0)

    def test_layer_info_query_and_payload_helpers(self) -> None:
        client = ArcGISClient()
        layer_payload = {
            "name": "Facilities",
            "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
            "maxRecordCount": 2000,
        }
        feature_payload = {
            "features": [
                {"attributes": {"OBJECTID": 1, "value": 12}, "geometry": {"x": -122.3, "y": 47.6}},
            ]
        }
        with patch.object(client, "get_json", side_effect=[layer_payload, feature_payload, feature_payload]) as get_json:
            self.assertEqual(client.layer_info(FoodSafetyLayer.FACILITIES).name, "Facilities")
            features = client.query(FeatureQuery(layer=FoodSafetyLayer.FACILITIES), DummyArcGISRecord)
            self.assertEqual(features[0].attributes.value, 12)
            self.assertEqual(features[0].geometry.x, -122.3)
            self.assertEqual(client.query_payload(FeatureQuery(layer=FoodSafetyLayer.FACILITIES)), feature_payload)
            self.assertEqual(get_json.call_count, 3)

    def test_query_all_fetches_pages_until_short_page(self) -> None:
        client = PagingClient(
            [
                [Feature(DummyRecord(1)), Feature(DummyRecord(2))],
                [Feature(DummyRecord(3))],
            ]
        )

        features = client.query_all(
            FeatureQuery(layer=FoodSafetyLayer.FACILITIES, offset=10),
            DummyRecord,
            page_size=2,
        )

        self.assertEqual([feature.attributes.value for feature in features], [1, 2, 3])
        self.assertEqual(client.calls, [(2, 10), (2, 12)])

    def test_query_all_payload_merges_pages_until_short_page(self) -> None:
        client = PayloadPagingClient(
            [
                {
                    "fields": [{"name": "OBJECTID"}],
                    "features": [{"attributes": {"OBJECTID": 1}}, {"attributes": {"OBJECTID": 2}}],
                },
                {
                    "fields": [{"name": "OBJECTID"}],
                    "features": [{"attributes": {"OBJECTID": 3}}],
                },
            ]
        )

        payload = client.query_all_payload(
            FeatureQuery(layer=FoodSafetyLayer.FACILITIES),
            page_size=2,
        )

        self.assertEqual(
            payload,
            {
                "fields": [{"name": "OBJECTID"}],
                "features": [
                    {"attributes": {"OBJECTID": 1}},
                    {"attributes": {"OBJECTID": 2}},
                    {"attributes": {"OBJECTID": 3}},
                ],
            },
        )
        self.assertEqual(client.calls, [(2, 0), (2, 2)])

    def test_query_all_payload_continues_after_short_exceeded_transfer_page(self) -> None:
        client = PayloadPagingClient(
            [
                {
                    "fields": [{"name": "OBJECTID"}],
                    "exceededTransferLimit": True,
                    "features": [{"attributes": {"OBJECTID": 1}}],
                },
                {
                    "fields": [{"name": "OBJECTID"}],
                    "exceededTransferLimit": False,
                    "features": [{"attributes": {"OBJECTID": 2}}],
                },
            ]
        )

        payload = client.query_all_payload(
            FeatureQuery(layer=FoodSafetyLayer.FACILITIES),
            page_size=2,
        )

        self.assertEqual(
            payload,
            {
                "fields": [{"name": "OBJECTID"}],
                "features": [
                    {"attributes": {"OBJECTID": 1}},
                    {"attributes": {"OBJECTID": 2}},
                ],
            },
        )
        self.assertEqual(client.calls, [(2, 0), (2, 1)])

        with self.assertRaises(FoodSafetyError):
            PayloadPagingClient([{"exceededTransferLimit": True, "features": []}]).query_all_payload(
                FeatureQuery(layer=FoodSafetyLayer.FACILITIES),
                page_size=2,
            )

    def test_query_all_payload_handles_count_ids_limits_and_invalid_paging(self) -> None:
        count_client = PayloadPagingClient([{"count": 2}])
        self.assertEqual(
            count_client.query_all_payload(
                FeatureQuery(layer=FoodSafetyLayer.FACILITIES, return_count_only=True),
                page_size=2,
            ),
            {"count": 2},
        )

        limited_client = PayloadPagingClient(
            [
                {
                    "features": [
                        {"attributes": {"OBJECTID": 1}},
                        {"attributes": {"OBJECTID": 2}},
                    ]
                }
            ]
        )
        payload = limited_client.query_all_payload(
            FeatureQuery(layer=FoodSafetyLayer.FACILITIES, offset=5),
            page_size=2,
            record_limit=2,
        )
        self.assertEqual(len(payload["features"]), 2)
        self.assertEqual(limited_client.calls, [(2, 5)])

        with self.assertRaises(FoodSafetyError):
            PayloadPagingClient([]).query_all_payload(FeatureQuery(layer=FoodSafetyLayer.FACILITIES), page_size=0)
        with self.assertRaises(FoodSafetyError):
            PayloadPagingClient([]).query_all_payload(FeatureQuery(layer=FoodSafetyLayer.FACILITIES), record_limit=0)

    def test_query_all_rejects_invalid_page_size(self) -> None:
        with self.assertRaises(FoodSafetyError):
            PagingClient([]).query_all(FeatureQuery(layer=FoodSafetyLayer.FACILITIES), DummyRecord, page_size=0)


class DummyArcGISRecord:
    def __init__(self, value: int) -> None:
        self.value = value

    @classmethod
    def from_arcgis(cls, attributes: dict) -> "DummyArcGISRecord":
        return cls(attributes["value"])


if __name__ == "__main__":
    unittest.main()
