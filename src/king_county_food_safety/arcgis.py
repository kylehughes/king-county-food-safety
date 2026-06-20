"""ArcGIS REST client and feature query construction."""

from __future__ import annotations

from dataclasses import dataclass, replace
from json import JSONDecodeError, loads
from socket import timeout as SocketTimeout
from typing import Any, Self
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from king_county_food_safety import constants
from king_county_food_safety.errors import ArcGISError, FoodSafetyError, HTTPStatusError, NetworkError
from king_county_food_safety.models import (
    Feature,
    FoodSafetyLayer,
    GeocodeCandidate,
    Geometry,
    LayerInfo,
    geometry_from_arcgis,
)


@dataclass(frozen=True, slots=True)
class SpatialFilter:
    """Point-buffer spatial filter for an ArcGIS feature query."""

    latitude: float
    longitude: float
    radius_miles: float


@dataclass(frozen=True, slots=True)
class FeatureQuery:
    """ArcGIS feature-layer query."""

    layer: FoodSafetyLayer
    where_clause: str = "1=1"
    fields: tuple[str, ...] = ("*",)
    return_geometry: bool = False
    order_by_fields: tuple[str, ...] = ()
    limit: int | None = None
    offset: int | None = None
    spatial_filter: SpatialFilter | None = None
    group_by_fields_for_statistics: tuple[str, ...] = ()
    out_statistics: str | None = None
    return_count_only: bool = False
    return_ids_only: bool = False

    def __post_init__(self) -> None:
        """Validate ArcGIS paging limits."""

        if self.limit is not None and not 1 <= self.limit <= 2000:
            raise FoodSafetyError(f"Invalid limit {self.limit}. ArcGIS accepts values from 1 through 2000.")

    def url(self) -> str:
        """Return the full request URL for this query."""

        return f"{self.layer.url}/query?{urlencode(self.params())}"

    def params(self) -> dict[str, str]:
        """Return ArcGIS query parameters."""

        params = {
            "f": "json",
            "where": self.where_clause,
            "outFields": ",".join(self.fields),
            "returnGeometry": "true" if self.return_geometry else "false",
        }

        if self.group_by_fields_for_statistics:
            params["groupByFieldsForStatistics"] = ",".join(self.group_by_fields_for_statistics)
        if self.limit is not None:
            params["resultRecordCount"] = str(self.limit)
        if self.offset is not None:
            params["resultOffset"] = str(self.offset)
        if self.order_by_fields:
            params["orderByFields"] = ",".join(self.order_by_fields)
        if self.out_statistics is not None:
            params["outStatistics"] = self.out_statistics
        if self.return_count_only:
            params["returnCountOnly"] = "true"
        if self.return_ids_only:
            params["returnIdsOnly"] = "true"
        if self.spatial_filter:
            params.update(
                {
                    "geometry": f"{self.spatial_filter.longitude},{self.spatial_filter.latitude}",
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "distance": str(self.spatial_filter.radius_miles),
                    "units": "esriSRUnit_StatuteMile",
                }
            )

        return params


class ArcGISClient:
    """Fetches and decodes ArcGIS REST responses."""

    def __init__(self, timeout: float = 30, retries: int = 0) -> None:
        if retries < 0:
            raise FoodSafetyError("Retries must be zero or greater.")
        if timeout <= 0:
            raise FoodSafetyError("Timeout must be greater than zero.")
        self.retries = retries
        self.timeout = timeout

    def count(self, query: FeatureQuery) -> int:
        """Fetch the count returned by an ArcGIS `returnCountOnly` query."""

        payload = self.get_json(query.url())
        try:
            return int(payload["count"])
        except KeyError as error:
            raise FoodSafetyError("ArcGIS count response did not include `count`.") from error

    def geocode(self, address: str, *, city: str | None = None, zip_code: str | None = None, limit: int = 5) -> list[GeocodeCandidate]:
        """Fetch King County geocoder candidates."""

        if not 1 <= limit <= 2000:
            raise FoodSafetyError(f"Invalid limit {limit}. ArcGIS accepts values from 1 through 2000.")

        params = {
            "f": "json",
            "maxLocations": str(limit),
            "outFields": "*",
            "outSR": "4326",
        }
        if city is None and zip_code is None:
            params["SingleLine"] = address
        else:
            params["Street"] = address
            if city is not None:
                params["City"] = city
            if zip_code is not None:
                params["ZIP"] = zip_code

        payload = self.get_json(f"{constants.KING_COUNTY_GEOCODER}/findAddressCandidates?{urlencode(params)}")
        return [GeocodeCandidate.from_arcgis(candidate) for candidate in payload.get("candidates", [])]

    def get_json(self, url: str) -> dict[str, Any]:
        """Fetch and decode JSON from a URL."""

        data = self.get_bytes(url)
        try:
            payload = loads(data.decode("utf-8"))
        except JSONDecodeError as error:
            raise FoodSafetyError(f"Could not decode JSON from {url}") from error

        if not isinstance(payload, dict):
            raise FoodSafetyError(f"Expected JSON object from {url}")

        if error_payload := payload.get("error"):
            raise ArcGISError(
                code=int(error_payload.get("code", 0)),
                message=str(error_payload.get("message", "Unknown ArcGIS error")),
                details=[str(detail) for detail in error_payload.get("details", [])],
            )

        return payload

    def get_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from a URL."""

        request = Request(url, headers={"User-Agent": "king-county-food-safety/0.1"})
        attempts = self.retries + 1
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    status = getattr(response, "status", 200)
                    if not 200 <= status <= 299:
                        raise HTTPStatusError(status, url)
                    return response.read()
            except HTTPError as error:
                raise HTTPStatusError(error.code, url) from error
            except URLError as error:
                if attempt == attempts - 1:
                    raise NetworkError(url, error.reason) from error
            except (OSError, SocketTimeout, TimeoutError) as error:
                if attempt == attempts - 1:
                    raise NetworkError(url, error) from error
        raise NetworkError(url, "request failed")  # pragma: no cover

    def layer_info(self, layer: FoodSafetyLayer) -> LayerInfo:
        """Fetch ArcGIS layer metadata."""

        payload = self.get_json(f"{layer.url}?{urlencode({'f': 'json'})}")
        return LayerInfo.from_arcgis(payload)

    def query(self, query: FeatureQuery, record_type: type[Self]) -> list[Feature[Self]]:
        """Execute and decode an ArcGIS feature query."""

        payload = self.query_payload(query)
        features: list[Feature[Self]] = []
        for feature in payload.get("features", []):
            features.append(
                Feature(
                    attributes=record_type.from_arcgis(feature["attributes"]),
                    geometry=geometry_from_arcgis(feature.get("geometry")),
                )
            )
        return features

    def query_payload(self, query: FeatureQuery) -> dict[str, Any]:
        """Execute a feature query and return the raw ArcGIS JSON payload."""

        return self.get_json(query.url())

    def query_all_payload(
        self,
        query: FeatureQuery,
        *,
        page_size: int = 2000,
        record_limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute a feature query until all pages, or an optional cap, have been fetched."""

        if query.return_count_only or query.return_ids_only:
            return self.query_payload(query)
        if not 1 <= page_size <= 2000:
            raise FoodSafetyError(f"Invalid page size {page_size}. ArcGIS accepts values from 1 through 2000.")
        if record_limit is not None and record_limit < 1:
            raise FoodSafetyError("Record limit must be at least 1.")

        features: list[dict[str, Any]] = []
        payload: dict[str, Any] | None = None
        offset = query.offset or 0
        while record_limit is None or len(features) < record_limit:
            remaining = page_size if record_limit is None else min(page_size, record_limit - len(features))
            page = self.query_payload(replace(query, limit=remaining, offset=offset))
            if payload is None:
                payload = {key: value for key, value in page.items() if key not in {"exceededTransferLimit", "features"}}
            page_features = page.get("features", [])
            features.extend(page_features)
            exceeded_transfer_limit = bool(page.get("exceededTransferLimit"))
            if exceeded_transfer_limit and not page_features:
                raise FoodSafetyError("ArcGIS reported more rows but returned an empty page.")
            if len(page_features) < remaining and not exceeded_transfer_limit:
                break
            offset += len(page_features)

        result = payload or {}
        result["features"] = features
        return result

    def query_all(self, query: FeatureQuery, record_type: type[Self], *, page_size: int = 2000) -> list[Feature[Self]]:
        """Execute a feature query until all pages have been fetched."""

        if not 1 <= page_size <= 2000:
            raise FoodSafetyError(f"Invalid page size {page_size}. ArcGIS accepts values from 1 through 2000.")

        features: list[Feature[Self]] = []
        offset = query.offset or 0
        while True:
            page = self.query(replace(query, limit=page_size, offset=offset), record_type)
            features.extend(page)
            if len(page) < page_size:
                return features
            offset += page_size
