"""Typed records returned by King County's ArcGIS services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from math import atan2, cos, pi, sin, sqrt
from typing import Any, Generic, TypeVar

import king_county_food_safety.sql as sql
from king_county_food_safety import constants
from king_county_food_safety.errors import FoodSafetyError

T = TypeVar("T")


class FoodSafetyLayer(StrEnum):
    """Public King County food-safety ArcGIS layers."""

    FACILITIES = "facilities"
    INSPECTIONS = "inspections"
    SEARCH = "search"
    VIOLATIONS = "violations"

    @property
    def display_name(self) -> str:
        """Return the layer display name."""

        match self:
            case FoodSafetyLayer.FACILITIES:
                return "Food facilities"
            case FoodSafetyLayer.INSPECTIONS:
                return "Inspections"
            case FoodSafetyLayer.SEARCH:
                return "Search view"
            case FoodSafetyLayer.VIOLATIONS:
                return "Violations"

    @property
    def url(self) -> str:
        """Return the full ArcGIS layer URL."""

        match self:
            case FoodSafetyLayer.FACILITIES:
                return f"{constants.FOOD_SAFETY_FEATURE_SERVER}/0"
            case FoodSafetyLayer.INSPECTIONS:
                return f"{constants.FOOD_SAFETY_FEATURE_SERVER}/1"
            case FoodSafetyLayer.SEARCH:
                return f"{constants.SEARCH_FEATURE_SERVER}/0"
            case FoodSafetyLayer.VIOLATIONS:
                return f"{constants.FOOD_SAFETY_FEATURE_SERVER}/2"

    @classmethod
    def from_cli(cls, value: str) -> FoodSafetyLayer:
        """Create a layer from a command-line value."""

        normalized = value.strip().lower()
        aliases = {
            "business": cls.FACILITIES,
            "businesses": cls.FACILITIES,
            "facilities": cls.FACILITIES,
            "facility": cls.FACILITIES,
            "restaurants": cls.FACILITIES,
            "history": cls.INSPECTIONS,
            "inspection": cls.INSPECTIONS,
            "inspections": cls.INSPECTIONS,
            "search": cls.SEARCH,
            "search-view": cls.SEARCH,
            "view": cls.SEARCH,
            "violation": cls.VIOLATIONS,
            "violations": cls.VIOLATIONS,
        }
        try:
            return aliases[normalized]
        except KeyError as error:
            raise FoodSafetyError(
                f"Unknown layer '{value}'. Expected facilities, inspections, violations, or search."
            ) from error


class FoodSafetyRating(Enum):
    """King County public food-safety rating categories."""

    EXCELLENT = "Excellent"
    GOOD = "Good"
    NEEDS_TO_IMPROVE = "Needs to Improve"
    NOT_AVAILABLE = ""
    OKAY = "Okay"

    @property
    def display_name(self) -> str:
        """Return a CLI-friendly display value."""

        return self.value or "Rating not available"

    @property
    def where_clause(self) -> str:
        """Return a SQL predicate matching this rating in the facilities layer."""

        if self is FoodSafetyRating.NOT_AVAILABLE:
            return "(Business_Grade IS NULL OR Business_Grade = '')"
        return f"Business_Grade = {sql.string_literal(self.value)}"

    @classmethod
    def from_cli(cls, value: str) -> FoodSafetyRating:
        """Create a rating from a command-line value."""

        normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
        aliases = {
            "excellent": cls.EXCELLENT,
            "good": cls.GOOD,
            "na": cls.NOT_AVAILABLE,
            "n-a": cls.NOT_AVAILABLE,
            "none": cls.NOT_AVAILABLE,
            "not-available": cls.NOT_AVAILABLE,
            "rating-not-available": cls.NOT_AVAILABLE,
            "unrated": cls.NOT_AVAILABLE,
            "needs-improve": cls.NEEDS_TO_IMPROVE,
            "needs-improvement": cls.NEEDS_TO_IMPROVE,
            "needs-to-improve": cls.NEEDS_TO_IMPROVE,
            "ok": cls.OKAY,
            "okay": cls.OKAY,
        }
        try:
            return aliases[normalized]
        except KeyError as error:
            raise FoodSafetyError(
                f"Unknown rating '{value}'. Expected excellent, good, okay, needs-to-improve, or not-available."
            ) from error


@dataclass(frozen=True, slots=True)
class Geometry:
    """Point geometry in WGS84 longitude/latitude coordinates."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Feature(Generic[T]):
    """ArcGIS feature wrapper."""

    attributes: T
    geometry: Geometry | None = None


@dataclass(frozen=True, slots=True)
class FacilityRecord:
    """King County food facility attributes."""

    business_address: str | None
    business_city: str | None
    business_establishment_description: str | None
    business_grade: str | None
    business_latitude: float | None
    business_longitude: float | None
    business_name: str | None
    business_phone: str | None
    business_program_identifier: str | None
    business_record_id: str | None
    business_status: str | None
    business_zip: str | None
    load_date_milliseconds: int | None
    object_id: int
    parcel_latitude: float | None
    parcel_longitude: float | None
    parcel_number: str | None

    @property
    def city_state_zip(self) -> str:
        """Return city, state, and ZIP formatted for display."""

        city = self.business_city or "-"
        zip_code = self.business_zip or "-"
        if city == "-":
            return zip_code
        if zip_code == "-":
            return city
        return f"{city}, WA {zip_code}"

    @property
    def display_rating(self) -> str:
        """Return a friendly rating label."""

        return self.business_grade or FoodSafetyRating.NOT_AVAILABLE.display_name

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> FacilityRecord:
        """Create a facility from ArcGIS attributes."""

        return cls(
            business_address=attributes.get("Business_Address"),
            business_city=attributes.get("Business_City"),
            business_establishment_description=attributes.get(
                "Business_Establishment_Descr"
            ),
            business_grade=attributes.get("Business_Grade"),
            business_latitude=_optional_float(attributes.get("Business_Location_Lat")),
            business_longitude=_optional_float(
                attributes.get("Businesss_Location_Long")
            ),
            business_name=attributes.get("Business_Name"),
            business_phone=attributes.get("Business_Phone"),
            business_program_identifier=attributes.get("Business_Program_Identifier"),
            business_record_id=attributes.get("Business_Record_ID"),
            business_status=attributes.get("Business_Status"),
            business_zip=attributes.get("Business_Location_Zip"),
            load_date_milliseconds=_optional_int(attributes.get("Load_DT_TM")),
            object_id=int(attributes["OBJECTID"]),
            parcel_latitude=_optional_float(attributes.get("Parcel_Lat")),
            parcel_longitude=_optional_float(attributes.get("Parcel_Lon")),
            parcel_number=attributes.get("Parcel_Number"),
        )


@dataclass(frozen=True, slots=True)
class InspectionRecord:
    """King County food-safety inspection attributes."""

    business_record_id: str | None
    inspection_business_name: str | None
    inspection_date: str | None
    inspection_result: str | None
    inspection_score: int | None
    inspection_serial_number: str | None
    inspection_type: str | None
    load_date_milliseconds: int | None
    object_id: int

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> InspectionRecord:
        """Create an inspection from ArcGIS attributes."""

        return cls(
            business_record_id=attributes.get("Business_Record_ID"),
            inspection_business_name=attributes.get("Inspection_Business_Name"),
            inspection_date=attributes.get("Inspection_Date"),
            inspection_result=attributes.get("Inspection_Result"),
            inspection_score=_optional_int(attributes.get("Inspection_Score")),
            inspection_serial_number=attributes.get("Inspection_Serial_Num"),
            inspection_type=attributes.get("Inspection_Type"),
            load_date_milliseconds=_optional_int(attributes.get("Load_DT_TM")),
            object_id=int(attributes["OBJECTID"]),
        )


@dataclass(frozen=True, slots=True)
class ViolationRecord:
    """King County inspection violation attributes."""

    inspection_serial_number: str | None
    load_date_milliseconds: int | None
    object_id: int
    violation_description: str | None
    violation_points: int | None
    violation_type: str | None

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> ViolationRecord:
        """Create a violation from ArcGIS attributes."""

        return cls(
            inspection_serial_number=attributes.get("Inspection_Serial_Num"),
            load_date_milliseconds=_optional_int(attributes.get("Load_DT_TM")),
            object_id=int(attributes["OBJECTID"]),
            violation_description=attributes.get("Violation_Descr"),
            violation_points=_optional_int(attributes.get("Violation_Points")),
            violation_type=attributes.get("Violation_Type"),
        )


@dataclass(frozen=True, slots=True)
class RatingSummary:
    """Grouped count for a food-safety rating."""

    count: int
    rating: str | None

    @property
    def display_rating(self) -> str:
        """Return a friendly rating label."""

        return self.rating or FoodSafetyRating.NOT_AVAILABLE.display_name

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> RatingSummary:
        """Create a rating summary from ArcGIS attributes."""

        return cls(
            count=int(attributes["count"]), rating=attributes.get("Business_Grade")
        )


@dataclass(frozen=True, slots=True)
class FieldInfo:
    """ArcGIS layer field metadata."""

    alias: str | None
    length: int | None
    name: str
    type: str

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> FieldInfo:
        """Create field metadata from ArcGIS attributes."""

        return cls(
            alias=attributes.get("alias"),
            length=_optional_int(attributes.get("length")),
            name=attributes["name"],
            type=attributes["type"],
        )


@dataclass(frozen=True, slots=True)
class LayerInfo:
    """ArcGIS layer metadata."""

    display_field: str | None
    fields: list[FieldInfo]
    geometry_type: str | None
    global_id_field: str | None
    max_record_count: int | None
    name: str
    object_id_field: str | None

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> LayerInfo:
        """Create layer metadata from ArcGIS attributes."""

        return cls(
            display_field=attributes.get("displayField"),
            fields=[
                FieldInfo.from_arcgis(field) for field in attributes.get("fields", [])
            ],
            geometry_type=attributes.get("geometryType"),
            global_id_field=attributes.get("globalIdField"),
            max_record_count=_optional_int(attributes.get("maxRecordCount")),
            name=attributes.get("name", ""),
            object_id_field=attributes.get("objectIdField"),
        )


@dataclass(frozen=True, slots=True)
class GeocodeCandidateAttributes:
    """Selected attributes returned by the King County geocoder."""

    address_type: str | None
    city: str | None
    match_address: str | None
    zip: str | None

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> GeocodeCandidateAttributes:
        """Create geocoder attributes from ArcGIS attributes."""

        return cls(
            address_type=attributes.get("Addr_type"),
            city=attributes.get("City"),
            match_address=attributes.get("Match_addr"),
            zip=attributes.get("ZIP"),
        )


@dataclass(frozen=True, slots=True)
class GeocodeCandidate:
    """King County geocoder candidate."""

    address: str
    attributes: GeocodeCandidateAttributes | None
    location: Geometry
    score: float

    @classmethod
    def from_arcgis(cls, attributes: dict[str, Any]) -> GeocodeCandidate:
        """Create a geocoder candidate from ArcGIS attributes."""

        raw_location = attributes["location"]
        raw_attributes = attributes.get("attributes")
        return cls(
            address=attributes["address"],
            attributes=GeocodeCandidateAttributes.from_arcgis(raw_attributes)
            if raw_attributes
            else None,
            location=Geometry(x=float(raw_location["x"]), y=float(raw_location["y"])),
            score=float(attributes["score"]),
        )


@dataclass(frozen=True, slots=True)
class InspectionWithViolations:
    """Inspection plus its violation rows."""

    inspection: Feature[InspectionRecord]
    violations: list[Feature[ViolationRecord]]


@dataclass(frozen=True, slots=True)
class FacilityDetail:
    """Facility plus optional inspection details."""

    facility: Feature[FacilityRecord]
    inspections: list[InspectionWithViolations] | None


@dataclass(frozen=True, slots=True)
class NearbyFacility:
    """Facility with computed distance from a search center."""

    distance_miles: float
    facility: Feature[FacilityRecord]


def geometry_from_arcgis(attributes: dict[str, Any] | None) -> Geometry | None:
    """Create point geometry from an ArcGIS feature, if present."""

    if not attributes:
        return None
    return Geometry(x=float(attributes["x"]), y=float(attributes["y"]))


def miles_between(first: Geometry, second: Geometry) -> float:
    """Return the Haversine distance between two WGS84 points in statute miles."""

    earth_radius_miles = 3958.7613
    latitude_delta = _degrees_to_radians(second.y - first.y)
    longitude_delta = _degrees_to_radians(second.x - first.x)
    first_latitude = _degrees_to_radians(first.y)
    second_latitude = _degrees_to_radians(second.y)

    a = sin(latitude_delta / 2) * sin(latitude_delta / 2) + sin(
        longitude_delta / 2
    ) * sin(longitude_delta / 2) * cos(first_latitude) * cos(second_latitude)
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return earth_radius_miles * c


def _degrees_to_radians(degrees: float) -> float:
    return degrees * pi / 180


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
