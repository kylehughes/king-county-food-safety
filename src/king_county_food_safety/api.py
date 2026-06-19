"""Typed operations over King County's public food-safety ArcGIS services."""

from __future__ import annotations

from king_county_food_safety import sql
from king_county_food_safety.arcgis import ArcGISClient, FeatureQuery, SpatialFilter
from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.models import (
    FacilityRecord,
    Feature,
    FoodSafetyLayer,
    FoodSafetyRating,
    GeocodeCandidate,
    InspectionRecord,
    LayerInfo,
    RatingSummary,
    ViolationRecord,
)


DEFAULT_BATCH_SIZE = 75
MAX_PAGE_SIZE = 2000


class FoodSafetyAPI:
    """High-level King County food-safety API wrapper."""

    PUBLIC_INSPECTION_CLAUSE = (
        "(Inspection_Type <> 'Consultation/Education') "
        "AND (Inspection_Result IN ('Satisfactory','Unsatisfactory'))"
    )

    def __init__(self, client: ArcGISClient | None = None) -> None:
        self.client = client or ArcGISClient()

    def count(self, layer: FoodSafetyLayer, where_clause: str = "1=1") -> int:
        """Count records in a layer."""

        return self.client.count(FeatureQuery(layer=layer, where_clause=where_clause, return_count_only=True))

    def facility(self, facility_id: str, *, include_inactive: bool = False) -> Feature[FacilityRecord]:
        """Return a facility by `Business_Record_ID` or `OBJECTID`."""

        query = FeatureQuery(
            layer=FoodSafetyLayer.FACILITIES,
            where_clause=sql.and_(
                self._facility_id_clause(facility_id),
                None if include_inactive else self._active_facility_clause,
            ),
            return_geometry=True,
            order_by_fields=("Business_Name ASC",),
            limit=1,
        )
        facilities = self.client.query(query, FacilityRecord)
        if not facilities:
            raise FoodSafetyError(f"No food facility found for '{facility_id}'.")
        return facilities[0]

    def geocode(self, address: str, *, city: str | None = None, zip_code: str | None = None, limit: int = 5) -> list[GeocodeCandidate]:
        """Geocode an address with King County's public locator."""

        return self.client.geocode(address, city=city, zip_code=zip_code, limit=limit)

    def inspections(
        self,
        facility_id: str,
        *,
        include_non_public: bool = False,
        include_inactive_facility: bool = False,
        limit: int = 25,
    ) -> list[Feature[InspectionRecord]]:
        """Return inspections for a facility business record ID or object ID."""

        facility = self.facility(facility_id, include_inactive=include_inactive_facility)
        business_record_id = facility.attributes.business_record_id
        if business_record_id is None:
            raise FoodSafetyError(f"No business record ID found for '{facility_id}'.")
        return self.inspections_by_business_record_id(
            business_record_id,
            include_non_public=include_non_public,
            limit=limit,
        )

    def inspections_by_business_record_id(
        self,
        business_record_id: str,
        *,
        include_non_public: bool = False,
        limit: int = 25,
    ) -> list[Feature[InspectionRecord]]:
        """Return inspections for a business record ID."""

        query = FeatureQuery(
            layer=FoodSafetyLayer.INSPECTIONS,
            where_clause=sql.and_(
                f"Business_Record_ID = {sql.string_literal(business_record_id)}",
                None if include_non_public else self.PUBLIC_INSPECTION_CLAUSE,
            ),
            fields=("*",),
            order_by_fields=("Inspection_Date DESC",),
            limit=limit,
        )
        return self.client.query(query, InspectionRecord)

    def inspections_for_facility_ids(
        self,
        facility_ids: list[str],
        *,
        include_non_public: bool = False,
        include_inactive_facility: bool = False,
        limit_per_facility: int | None = None,
    ) -> list[Feature[InspectionRecord]]:
        """Return inspections for many facility IDs using batched ArcGIS queries."""

        business_record_ids = self._business_record_ids_for_facility_ids(
            facility_ids,
            include_inactive=include_inactive_facility,
        )
        inspections: list[Feature[InspectionRecord]] = []
        for chunk in self._chunks(business_record_ids, DEFAULT_BATCH_SIZE):
            query = FeatureQuery(
                layer=FoodSafetyLayer.INSPECTIONS,
                where_clause=sql.and_(
                    f"Business_Record_ID IN ({self._literal_list(chunk)})",
                    None if include_non_public else self.PUBLIC_INSPECTION_CLAUSE,
                ),
                fields=("*",),
                order_by_fields=("Inspection_Date DESC",),
            )
            inspections.extend(self.client.query_all(query, InspectionRecord, page_size=MAX_PAGE_SIZE))

        inspections.sort(
            key=lambda inspection: (
                inspection.attributes.business_record_id or "",
                inspection.attributes.inspection_date or "",
                inspection.attributes.object_id,
            ),
            reverse=True,
        )
        if limit_per_facility is None:
            return inspections
        return self._limit_inspections_per_facility(inspections, limit_per_facility)

    def layer_info(self, layer: FoodSafetyLayer) -> LayerInfo:
        """Return layer metadata."""

        return self.client.layer_info(layer)

    def nearby_facilities(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_miles: float,
        rating: FoodSafetyRating | None = None,
        include_inactive: bool = False,
        limit: int = 25,
    ) -> list[Feature[FacilityRecord]]:
        """Return facilities within a radius of a coordinate."""

        query = FeatureQuery(
            layer=FoodSafetyLayer.FACILITIES,
            where_clause=sql.and_(
                None if include_inactive else self._active_facility_clause,
                rating.where_clause if rating else None,
            ),
            return_geometry=True,
            order_by_fields=("Business_Name ASC",),
            limit=limit,
            spatial_filter=SpatialFilter(latitude=latitude, longitude=longitude, radius_miles=radius_miles),
        )
        return self.client.query(query, FacilityRecord)

    def rating_summary(self, *, include_inactive: bool = False) -> list[Feature[RatingSummary]]:
        """Return grouped facility counts by rating."""

        query = FeatureQuery(
            layer=FoodSafetyLayer.FACILITIES,
            where_clause="1=1" if include_inactive else self._active_facility_clause,
            order_by_fields=("Business_Grade ASC",),
            group_by_fields_for_statistics=("Business_Grade",),
            out_statistics='[{"statisticType":"count","onStatisticField":"OBJECTID","outStatisticFieldName":"count"}]',
        )
        return self.client.query(query, RatingSummary)

    def search_facilities(
        self,
        text: str | None,
        *,
        city: str | None = None,
        zip_code: str | None = None,
        rating: FoodSafetyRating | None = None,
        include_inactive: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Feature[FacilityRecord]]:
        """Search active food facilities by name, address, city, ZIP, and rating."""

        query = FeatureQuery(
            layer=FoodSafetyLayer.FACILITIES,
            where_clause=sql.and_(
                None if include_inactive else self._active_facility_clause,
                self._search_text_clause(text),
                sql.contains("Business_City", city) if city else None,
                f"Business_Location_Zip = {sql.string_literal(zip_code)}" if zip_code else None,
                rating.where_clause if rating else None,
            ),
            return_geometry=True,
            order_by_fields=("Business_Name ASC", "Business_Address ASC"),
            limit=limit,
            offset=offset,
        )
        return self.client.query(query, FacilityRecord)

    def violations(self, inspection_serial_number: str) -> list[Feature[ViolationRecord]]:
        """Return violations for an inspection serial number."""

        query = FeatureQuery(
            layer=FoodSafetyLayer.VIOLATIONS,
            where_clause=f"Inspection_Serial_Num = {sql.string_literal(inspection_serial_number)}",
            fields=("*",),
            order_by_fields=("Violation_Points DESC", "Violation_Descr ASC"),
        )
        return self.client.query(query, ViolationRecord)

    def violations_for_inspection_serial_numbers(
        self,
        inspection_serial_numbers: list[str],
    ) -> list[Feature[ViolationRecord]]:
        """Return violations for many inspection serial numbers using batched ArcGIS queries."""

        serials = self._unique_non_empty(inspection_serial_numbers)
        violations: list[Feature[ViolationRecord]] = []
        for chunk in self._chunks(serials, DEFAULT_BATCH_SIZE):
            query = FeatureQuery(
                layer=FoodSafetyLayer.VIOLATIONS,
                where_clause=f"Inspection_Serial_Num IN ({self._literal_list(chunk)})",
                fields=("*",),
                order_by_fields=("Inspection_Serial_Num ASC", "Violation_Points DESC", "Violation_Descr ASC"),
            )
            violations.extend(self.client.query_all(query, ViolationRecord, page_size=MAX_PAGE_SIZE))
        return violations

    @property
    def _active_facility_clause(self) -> str:
        return "Business_Status = 'Active'"

    def _facility_id_clause(self, facility_id: str) -> str:
        if facility_id.isdecimal():
            return sql.or_(
                f"OBJECTID = {facility_id}",
                f"Business_Record_ID = {sql.string_literal(facility_id)}",
            )
        return f"Business_Record_ID = {sql.string_literal(facility_id)}"

    def _business_record_ids_for_facility_ids(self, facility_ids: list[str], *, include_inactive: bool) -> list[str]:
        ids = self._unique_non_empty(facility_ids)
        business_record_ids = [facility_id for facility_id in ids if not facility_id.isdecimal()]
        object_ids = [facility_id for facility_id in ids if facility_id.isdecimal()]

        if object_ids:
            for chunk in self._chunks(object_ids, DEFAULT_BATCH_SIZE):
                clauses = [
                    f"OBJECTID IN ({','.join(chunk)})",
                    None if include_inactive else self._active_facility_clause,
                ]
                query = FeatureQuery(
                    layer=FoodSafetyLayer.FACILITIES,
                    where_clause=sql.and_(*clauses),
                    fields=("Business_Record_ID", "OBJECTID", "Business_Status"),
                    limit=MAX_PAGE_SIZE,
                )
                facilities = self.client.query(query, FacilityRecord)
                business_record_ids.extend(
                    facility.attributes.business_record_id
                    for facility in facilities
                    if facility.attributes.business_record_id is not None
                )

        return self._unique_non_empty(business_record_ids)

    @staticmethod
    def _chunks(values: list[str], size: int) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    @staticmethod
    def _limit_inspections_per_facility(
        inspections: list[Feature[InspectionRecord]],
        limit_per_facility: int,
    ) -> list[Feature[InspectionRecord]]:
        counts: dict[str, int] = {}
        limited: list[Feature[InspectionRecord]] = []
        for inspection in inspections:
            business_record_id = inspection.attributes.business_record_id or ""
            count = counts.get(business_record_id, 0)
            if count >= limit_per_facility:
                continue
            counts[business_record_id] = count + 1
            limited.append(inspection)
        return limited

    @staticmethod
    def _literal_list(values: list[str]) -> str:
        return ",".join(sql.string_literal(value) for value in values)

    def _search_text_clause(self, text: str | None) -> str | None:
        if text is None or not text.strip():
            return None
        value = text.strip()
        return sql.or_(
            sql.contains("Business_Address", value),
            sql.contains("Business_City", value),
            sql.contains("Business_Name", value),
            sql.contains("Business_Program_Identifier", value),
            sql.contains("Business_Location_Zip", value),
        )

    @staticmethod
    def _unique_non_empty(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result
