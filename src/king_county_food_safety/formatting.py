"""CLI output formatting and normalized record projection."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.models import (
    FacilityDetail,
    FacilityRecord,
    Feature,
    FieldInfo,
    FoodSafetyLayer,
    GeocodeCandidate,
    Geometry,
    InspectionRecord,
    InspectionWithViolations,
    LayerInfo,
    NearbyFacility,
    RatingSummary,
    ViolationRecord,
)

FACILITY_FIELDS = [
    "business_record_id",
    "object_id",
    "rating",
    "business_name",
    "business_address",
    "business_city",
    "business_zip",
    "business_status",
]

GEOCODE_FIELDS = [
    "score",
    "address",
    "latitude",
    "longitude",
    "address_type",
]

INSPECTION_FIELDS = [
    "inspection_date",
    "inspection_result",
    "inspection_score",
    "inspection_type",
    "inspection_serial_number",
    "business_record_id",
]

LAYER_FIELDS = [
    "layer",
    "name",
    "url",
]

LAYER_INFO_FIELDS = [
    "name",
    "type",
    "alias",
    "length",
]

NEARBY_FIELDS = [
    "distance_miles",
    *FACILITY_FIELDS,
]

RATING_FIELDS = [
    "rating",
    "count",
]

VIOLATION_FIELDS = [
    "inspection_serial_number",
    "violation_type",
    "violation_points",
    "violation_description",
]

INSPECTION_VIOLATION_FIELDS = [
    *INSPECTION_FIELDS,
    "violation_type",
    "violation_points",
    "violation_description",
    "violation_object_id",
]

MACHINE_FORMATS = {"csv", "json", "jsonl", "tsv"}


def coordinate_display(geometry: Geometry | None) -> str:
    """Return coordinates as latitude, longitude text."""

    if geometry is None:
        return "-"
    return f"{geometry.y:.6f}, {geometry.x:.6f}"


def date_time(milliseconds: int | None) -> str | None:
    """Return an ISO-8601 UTC timestamp from ArcGIS milliseconds."""

    if milliseconds is None:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat().replace("+00:00", "Z")


def display(value: Any) -> str:
    """Return display text for optional values."""

    if value is None or value == "":
        return "-"
    return str(value)


def emit_records(
    records: list[dict[str, Any]],
    *,
    output_format: str,
    default_fields: list[str],
    fields: list[str] | None = None,
) -> None:
    """Print normalized records in the requested format."""

    selected_fields = _selected_fields(records, default_fields=default_fields, fields=fields)
    projected = [_project(record, selected_fields) for record in records]

    if output_format == "csv":
        print_delimited(selected_fields, projected, delimiter=",")
    elif output_format == "json":
        print(json.dumps(projected, indent=2, sort_keys=True))
    elif output_format == "jsonl":
        for record in projected:
            print(json.dumps(record, sort_keys=True))
    elif output_format == "tsv":
        print_delimited(selected_fields, projected, delimiter="\t")
    else:
        print_table(selected_fields, [[_text(record.get(field)) for field in selected_fields] for record in projected])


def facility_record(facility: Feature[FacilityRecord]) -> dict[str, Any]:
    """Return a normalized facility record."""

    record = facility.attributes
    return {
        "business_address": record.business_address,
        "business_city": record.business_city,
        "business_establishment_description": record.business_establishment_description,
        "business_latitude": record.business_latitude,
        "business_longitude": record.business_longitude,
        "business_name": record.business_name,
        "business_phone": record.business_phone,
        "business_program_identifier": record.business_program_identifier,
        "business_record_id": record.business_record_id,
        "business_status": record.business_status,
        "business_zip": record.business_zip,
        "latitude": facility.geometry.y if facility.geometry else record.business_latitude,
        "load_date": date_time(record.load_date_milliseconds),
        "longitude": facility.geometry.x if facility.geometry else record.business_longitude,
        "object_id": record.object_id,
        "parcel_latitude": record.parcel_latitude,
        "parcel_longitude": record.parcel_longitude,
        "parcel_number": record.parcel_number,
        "rating": record.display_rating,
    }


def field_info_record(field: FieldInfo) -> dict[str, Any]:
    """Return a normalized layer field metadata record."""

    return {
        "alias": field.alias,
        "length": field.length,
        "name": field.name,
        "type": field.type,
    }


def geocode_record(candidate: GeocodeCandidate) -> dict[str, Any]:
    """Return a normalized geocoder candidate record."""

    return {
        "address": candidate.address,
        "address_type": candidate.attributes.address_type if candidate.attributes else None,
        "city": candidate.attributes.city if candidate.attributes else None,
        "latitude": candidate.location.y,
        "longitude": candidate.location.x,
        "match_address": candidate.attributes.match_address if candidate.attributes else None,
        "score": candidate.score,
        "zip": candidate.attributes.zip if candidate.attributes else None,
    }


def inspection_record(inspection: Feature[InspectionRecord]) -> dict[str, Any]:
    """Return a normalized inspection record."""

    record = inspection.attributes
    return {
        "business_record_id": record.business_record_id,
        "inspection_business_name": record.inspection_business_name,
        "inspection_date": record.inspection_date,
        "inspection_result": record.inspection_result,
        "inspection_score": record.inspection_score,
        "inspection_serial_number": record.inspection_serial_number,
        "inspection_type": record.inspection_type,
        "load_date": date_time(record.load_date_milliseconds),
        "object_id": record.object_id,
    }


def inspection_violation_records(items: list[InspectionWithViolations]) -> list[dict[str, Any]]:
    """Return normalized inspection/violation join records."""

    records: list[dict[str, Any]] = []
    for item in items:
        base_record = inspection_record(item.inspection)
        if not item.violations:
            records.append(
                {
                    **base_record,
                    "violation_description": None,
                    "violation_object_id": None,
                    "violation_points": None,
                    "violation_type": None,
                }
            )
            continue
        for violation in item.violations:
            violation_data = violation_record(violation)
            records.append(
                {
                    **base_record,
                    "violation_description": violation_data["violation_description"],
                    "violation_object_id": violation_data["object_id"],
                    "violation_points": violation_data["violation_points"],
                    "violation_type": violation_data["violation_type"],
                }
            )
    return records


def layer_record(layer: FoodSafetyLayer) -> dict[str, Any]:
    """Return a normalized layer URL record."""

    return {
        "layer": layer.value,
        "name": layer.display_name,
        "url": layer.url,
    }


def nearby_record(item: NearbyFacility) -> dict[str, Any]:
    """Return a normalized nearby facility record."""

    return {
        "distance_miles": round(item.distance_miles, 4),
        **facility_record(item.facility),
    }


def print_facility_detail(
    detail: FacilityDetail,
    *,
    output_format: str,
    fields: list[str] | None = None,
) -> None:
    """Print one facility plus optional inspection details."""

    if output_format in MACHINE_FORMATS or fields is not None:
        emit_records(
            [facility_record(detail.facility)],
            output_format=output_format,
            default_fields=FACILITY_FIELDS,
            fields=fields,
        )
        return

    facility = detail.facility.attributes
    rows = [
        ["Name", display(facility.business_name)],
        ["Rating", facility.display_rating],
        ["Business Record ID", display(facility.business_record_id)],
        ["Object ID", str(facility.object_id)],
        ["Status", display(facility.business_status)],
        ["Address", display(facility.business_address)],
        ["City", facility.city_state_zip],
        ["Type", display(facility.business_establishment_description)],
        ["Program", display(facility.business_program_identifier)],
        ["Phone", display(facility.business_phone)],
        ["Parcel", display(facility.parcel_number)],
        ["Coordinates", coordinate_display(detail.facility.geometry)],
        ["Loaded", display(date_time(facility.load_date_milliseconds))],
    ]
    print_table(["Field", "Value"], rows)

    if detail.inspections is not None:
        print()
        emit_records(
            inspection_violation_records(detail.inspections),
            output_format="table",
            default_fields=INSPECTION_VIOLATION_FIELDS,
        )


def print_json(value: Any) -> None:
    """Print JSON for already-normalized values."""

    print(json.dumps(value, indent=2, sort_keys=True))


def print_delimited(headers: list[str], records: list[dict[str, Any]], *, delimiter: str) -> None:
    """Print CSV or TSV records."""

    stream = StringIO()
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows([_text(record.get(header)) for header in headers] for record in records)
    print(stream.getvalue(), end="")


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a simple aligned table."""

    if not rows:
        print("No records found.")
        return

    widths = [
        max(len(headers[index]), *(len(row[index]) if index < len(row) else 0 for row in rows))
        for index in range(len(headers))
    ]
    print(_table_row(headers, widths))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print(_table_row(row, widths))


def rating_summary_record(summary: Feature[RatingSummary]) -> dict[str, Any]:
    """Return a normalized rating summary record."""

    return {
        "count": summary.attributes.count,
        "rating": summary.attributes.display_rating,
    }


def violation_record(violation: Feature[ViolationRecord]) -> dict[str, Any]:
    """Return a normalized violation record."""

    record = violation.attributes
    return {
        "inspection_serial_number": record.inspection_serial_number,
        "load_date": date_time(record.load_date_milliseconds),
        "object_id": record.object_id,
        "violation_description": record.violation_description,
        "violation_points": record.violation_points,
        "violation_type": record.violation_type,
    }


def _all_fields(records: list[dict[str, Any]], fallback: list[str]) -> list[str]:
    fields: list[str] = []
    for field in fallback:
        if field not in fields:
            fields.append(field)
    for record in records:
        for field in record:
            if field not in fields:
                fields.append(field)
    return fields


def _project(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {field: record.get(field) for field in fields}


def _selected_fields(
    records: list[dict[str, Any]],
    *,
    default_fields: list[str],
    fields: list[str] | None,
) -> list[str]:
    available_fields = _all_fields(records, default_fields)
    if fields is None:
        return default_fields if default_fields else available_fields
    if fields == ["*"]:
        return available_fields

    unknown_fields = [field for field in fields if field not in available_fields]
    if unknown_fields:
        raise FoodSafetyError(
            "Unknown field(s): "
            f"{', '.join(unknown_fields)}. Available fields: {', '.join(available_fields)}."
        )
    return fields


def _table_row(values: list[str], widths: list[int]) -> str:
    return "  ".join((values[index] if index < len(values) else "").ljust(widths[index]) for index in range(len(widths)))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)
