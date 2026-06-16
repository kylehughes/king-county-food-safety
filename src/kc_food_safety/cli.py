"""Command-line interface for King County food safety ratings."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from kc_food_safety.api import FoodSafetyAPI
from kc_food_safety.arcgis import FeatureQuery, SpatialFilter
from kc_food_safety.errors import FoodSafetyError
from kc_food_safety.formatting import (
    FACILITY_FIELDS,
    GEOCODE_FIELDS,
    INSPECTION_FIELDS,
    INSPECTION_VIOLATION_FIELDS,
    LAYER_FIELDS,
    LAYER_INFO_FIELDS,
    NEARBY_FIELDS,
    RATING_FIELDS,
    VIOLATION_FIELDS,
    emit_records,
    facility_record,
    field_info_record,
    geocode_record,
    inspection_record,
    inspection_violation_records,
    layer_record,
    nearby_record,
    print_facility_detail,
    print_table,
    rating_summary_record,
    violation_record,
)
from kc_food_safety.models import (
    FacilityDetail,
    FoodSafetyLayer,
    FoodSafetyRating,
    Geometry,
    InspectionWithViolations,
    NearbyFacility,
    miles_between,
)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        args.handler(args, FoodSafetyAPI())
    except FoodSafetyError as error:
        parser.exit(1, f"{error}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the root argument parser."""

    parser = argparse.ArgumentParser(
        prog="kc-food-safety",
        description="King County food safety ratings, inspections, violations, geocoding, and ArcGIS queries.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    output_parent = argparse.ArgumentParser(add_help=False)
    output_group = output_parent.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_const", const="json", dest="output_format", help="Print JSON.")
    output_group.add_argument("--jsonl", action="store_const", const="jsonl", dest="output_format", help="Print JSON Lines.")
    output_group.add_argument("--csv", action="store_const", const="csv", dest="output_format", help="Print CSV.")
    output_group.add_argument("--tsv", action="store_const", const="tsv", dest="output_format", help="Print TSV.")
    output_parent.add_argument("--fields", type=_fields, help="Comma-separated output fields. Use '*' for all fields.")
    output_parent.set_defaults(output_format="table")

    search = subparsers.add_parser("search", parents=[output_parent], help="Search food facilities.")
    search.add_argument("text", nargs="*", help="Name, address, city, or ZIP text.")
    search.add_argument("--city", help="Filter by city.")
    search.add_argument("--include-inactive", action="store_true", help="Include inactive facility records.")
    search.add_argument("--limit", type=_limit, default=25, help="Limit records, 1 through 2000.")
    search.add_argument("--offset", type=int, default=0, help="ArcGIS result offset.")
    search.add_argument("--rating", type=_rating, help="Filter by rating.")
    search.add_argument("--zip", dest="zip_code", help="Filter by ZIP.")
    search.set_defaults(handler=_search)

    facility = subparsers.add_parser("facility", aliases=["get"], parents=[output_parent], help="Show one facility.")
    facility.add_argument("facility_id", help="Business_Record_ID or OBJECTID.")
    facility.add_argument("--all-inspections", action="store_true", help="Include non-public inspection rows.")
    facility.add_argument("--include-inactive", action="store_true", help="Allow inactive facility records.")
    facility.add_argument("--limit", type=_limit, default=10, help="Inspection limit when included.")
    facility.add_argument("--with-inspections", action="store_true", help="Include inspection history.")
    facility.add_argument("--with-violations", action="store_true", help="Include violations for included inspections.")
    facility.set_defaults(handler=_facility)

    inspections = subparsers.add_parser(
        "inspections",
        aliases=["history"],
        parents=[output_parent],
        help="Show inspection history.",
    )
    inspections.add_argument("facility_id", nargs="?", help="Business_Record_ID or OBJECTID.")
    inspections.add_argument("--all", action="store_true", dest="include_non_public", help="Include non-public rows.")
    inspections.add_argument("--include-inactive", action="store_true", help="Allow inactive facility records.")
    inspections.add_argument("--limit", type=_limit, default=25, help="Limit inspection records.")
    inspections.add_argument("--stdin", action="store_true", help="Read facility IDs from stdin, one per line.")
    inspections.add_argument("--with-violations", action="store_true", help="Include violation rows.")
    inspections.set_defaults(handler=_inspections)

    violations = subparsers.add_parser("violations", parents=[output_parent], help="Show inspection violations.")
    violations.add_argument("inspection_serial_number", nargs="?", help="Inspection_Serial_Num.")
    violations.add_argument("--stdin", action="store_true", help="Read inspection serial numbers from stdin, one per line.")
    violations.set_defaults(handler=_violations)

    ratings = subparsers.add_parser("ratings", aliases=["summary"], parents=[output_parent], help="Summarize ratings.")
    ratings.add_argument("--include-inactive", action="store_true", help="Include inactive facility records.")
    ratings.set_defaults(handler=_ratings)

    near = subparsers.add_parser("near", aliases=["nearby"], parents=[output_parent], help="Find nearby facilities.")
    near.add_argument("address", nargs="*", help="Address to geocode.")
    near.add_argument("--city", help="City hint for address geocoding.")
    near.add_argument("--include-inactive", action="store_true", help="Include inactive facility records.")
    near.add_argument("--lat", "--latitude", dest="latitude", type=float, help="Search center latitude.")
    near.add_argument("--limit", type=_limit, default=25, help="Limit displayed records.")
    near.add_argument("--lon", "--longitude", dest="longitude", type=float, help="Search center longitude.")
    near.add_argument("--radius", type=float, default=0.5, help="Radius in statute miles.")
    near.add_argument("--rating", type=_rating, help="Filter by rating.")
    near.add_argument("--zip", dest="zip_code", help="ZIP hint for address geocoding.")
    near.set_defaults(handler=_near)

    geocode = subparsers.add_parser("geocode", parents=[output_parent], help="Geocode a King County address.")
    geocode.add_argument("address", nargs="*", help="Address text.")
    geocode.add_argument("--city", help="City hint.")
    geocode.add_argument("--limit", type=_limit, default=5, help="Limit geocoder candidates.")
    geocode.add_argument("--zip", dest="zip_code", help="ZIP hint.")
    geocode.set_defaults(handler=_geocode)

    count = subparsers.add_parser("count", parents=[output_parent], help="Count records in a layer.")
    count.add_argument("layer", type=_layer, help="facilities, inspections, violations, or search.")
    count.add_argument("--where", dest="where_clause", default="1=1", help="ArcGIS SQL predicate.")
    count.set_defaults(handler=_count)

    metadata = subparsers.add_parser("metadata", aliases=["schema"], parents=[output_parent], help="Show layer metadata.")
    metadata.add_argument("layer", nargs="?", type=_layer, help="Layer to inspect.")
    metadata.set_defaults(handler=_metadata)

    query = subparsers.add_parser("query", aliases=["raw"], help="Run a raw ArcGIS feature-layer query.")
    query.add_argument("layer", type=_layer, help="facilities, inspections, violations, or search.")
    query.add_argument("--count", action="store_true", help="Return count only.")
    query.add_argument("--fields", default="*", help="Comma-separated outFields value.")
    query.add_argument("--geometry", action="store_true", help="Return geometry.")
    query.add_argument("--ids", action="store_true", help="Return object IDs only.")
    query.add_argument("--lat", "--latitude", dest="latitude", type=float, help="Spatial query center latitude.")
    query.add_argument("--limit", type=_limit, help="ArcGIS resultRecordCount.")
    query.add_argument("--lon", "--longitude", dest="longitude", type=float, help="Spatial query center longitude.")
    query.add_argument("--offset", type=int, help="ArcGIS resultOffset.")
    query.add_argument("--order-by", dest="order_by", help="ArcGIS orderByFields value.")
    query.add_argument("--radius", type=float, default=0.5, help="Spatial query radius.")
    query.add_argument("--where", dest="where_clause", default="1=1", help="ArcGIS SQL predicate.")
    query.set_defaults(handler=_query)

    return parser


def _count(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    count = api.count(args.layer, args.where_clause)
    if args.output_format == "table" and args.fields is None:
        print(count)
        return
    emit_records(
        [
            {
                "count": count,
                "layer": args.layer.value,
                "where": args.where_clause,
            }
        ],
        output_format=args.output_format,
        default_fields=["count"],
        fields=args.fields,
    )


def _facility(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    facility = api.facility(args.facility_id, include_inactive=args.include_inactive)
    include_inspections = args.with_inspections or args.with_violations
    details = None
    if include_inspections:
        inspections = api.inspections(
            args.facility_id,
            include_non_public=args.all_inspections,
            include_inactive_facility=args.include_inactive,
            limit=args.limit,
        )
        details = _inspection_details(api, inspections, include_violations=args.with_violations)
    print_facility_detail(
        FacilityDetail(facility=facility, inspections=details),
        output_format=args.output_format,
        fields=args.fields,
    )


def _geocode(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    address = _address(args.address)
    candidates = api.geocode(address, city=args.city, zip_code=args.zip_code, limit=args.limit)
    emit_records(
        [geocode_record(candidate) for candidate in candidates],
        output_format=args.output_format,
        default_fields=GEOCODE_FIELDS,
        fields=args.fields,
    )


def _inspections(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    facility_ids = _input_values(args.facility_id, use_stdin=args.stdin, name="facility id")
    if args.stdin:
        inspections = api.inspections_for_facility_ids(
            facility_ids,
            include_non_public=args.include_non_public,
            include_inactive_facility=args.include_inactive,
            limit_per_facility=args.limit,
        )
    else:
        inspections = api.inspections(
            facility_ids[0],
            include_non_public=args.include_non_public,
            include_inactive_facility=args.include_inactive,
            limit=args.limit,
        )
    if args.with_violations:
        emit_records(
            inspection_violation_records(_inspection_details(api, inspections, include_violations=True)),
            output_format=args.output_format,
            default_fields=INSPECTION_VIOLATION_FIELDS,
            fields=args.fields,
        )
    else:
        emit_records(
            [inspection_record(inspection) for inspection in inspections],
            output_format=args.output_format,
            default_fields=INSPECTION_FIELDS,
            fields=args.fields,
        )


def _metadata(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    if args.layer is None:
        emit_records(
            [layer_record(layer) for layer in FoodSafetyLayer],
            output_format=args.output_format,
            default_fields=LAYER_FIELDS,
            fields=args.fields,
        )
        return
    info = api.layer_info(args.layer)
    emit_records(
        [field_info_record(field) for field in info.fields],
        output_format=args.output_format,
        default_fields=LAYER_INFO_FIELDS,
        fields=args.fields,
    )


def _near(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    center = _near_center(args, api)
    facilities = api.nearby_facilities(
        latitude=center.y,
        longitude=center.x,
        radius_miles=args.radius,
        rating=args.rating,
        include_inactive=args.include_inactive,
        limit=2000,
    )
    nearby = sorted(
        [
            NearbyFacility(
                distance_miles=miles_between(center, facility.geometry) if facility.geometry else float("inf"),
                facility=facility,
            )
            for facility in facilities
        ],
        key=lambda item: item.distance_miles,
    )[: args.limit]
    emit_records(
        [nearby_record(item) for item in nearby],
        output_format=args.output_format,
        default_fields=NEARBY_FIELDS,
        fields=args.fields,
    )


def _query(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    query = FeatureQuery(
        layer=args.layer,
        where_clause=args.where_clause,
        fields=tuple(_comma_list(args.fields)) or ("*",),
        return_geometry=args.geometry,
        order_by_fields=tuple(_comma_list(args.order_by)),
        limit=args.limit,
        offset=args.offset,
        spatial_filter=_spatial_filter(args),
        return_count_only=args.count,
        return_ids_only=args.ids,
    )
    payload = api.client.get_json(query.url())
    print(json.dumps(payload, indent=2, sort_keys=True))


def _ratings(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    emit_records(
        [rating_summary_record(summary) for summary in api.rating_summary(include_inactive=args.include_inactive)],
        output_format=args.output_format,
        default_fields=RATING_FIELDS,
        fields=args.fields,
    )


def _search(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    facilities = api.search_facilities(
        " ".join(args.text) if args.text else None,
        city=args.city,
        zip_code=args.zip_code,
        rating=args.rating,
        include_inactive=args.include_inactive,
        limit=args.limit,
        offset=args.offset,
    )
    emit_records(
        [facility_record(facility) for facility in facilities],
        output_format=args.output_format,
        default_fields=FACILITY_FIELDS,
        fields=args.fields,
    )


def _violations(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    serials = _input_values(args.inspection_serial_number, use_stdin=args.stdin, name="inspection serial number")
    violations = (
        api.violations_for_inspection_serial_numbers(serials)
        if args.stdin
        else api.violations(serials[0])
    )
    emit_records(
        [violation_record(violation) for violation in violations],
        output_format=args.output_format,
        default_fields=VIOLATION_FIELDS,
        fields=args.fields,
    )


def _address(parts: list[str]) -> str:
    address = " ".join(parts).strip()
    if not address:
        raise FoodSafetyError("Missing required argument: address.")
    return address


def _comma_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _fields(value: str) -> list[str]:
    fields = _comma_list(value)
    if not fields:
        raise argparse.ArgumentTypeError("expected at least one field")
    return fields


def _input_values(value: str | None, *, use_stdin: bool, name: str) -> list[str]:
    values: list[str] = []
    if use_stdin:
        values.extend(line.strip() for line in sys.stdin if line.strip())
    if value is not None and value.strip():
        values.append(value.strip())
    if not values:
        raise FoodSafetyError(f"Missing required argument: {name}.")

    seen: set[str] = set()
    unique_values: list[str] = []
    for item in values:
        if item not in seen:
            seen.add(item)
            unique_values.append(item)
    return unique_values


def _inspection_details(
    api: FoodSafetyAPI,
    inspections: list,
    *,
    include_violations: bool,
) -> list[InspectionWithViolations]:
    if not include_violations:
        return [InspectionWithViolations(inspection=inspection, violations=[]) for inspection in inspections]

    serials = [
        inspection.attributes.inspection_serial_number
        for inspection in inspections
        if inspection.attributes.inspection_serial_number
    ]
    violations_by_serial = defaultdict(list)
    for violation in api.violations_for_inspection_serial_numbers(serials):
        serial = violation.attributes.inspection_serial_number
        if serial:
            violations_by_serial[serial].append(violation)

    details: list[InspectionWithViolations] = []
    for inspection in inspections:
        serial = inspection.attributes.inspection_serial_number
        violations = violations_by_serial.get(serial, []) if serial else []
        details.append(InspectionWithViolations(inspection=inspection, violations=violations))
    return details


def _layer(value: str) -> FoodSafetyLayer:
    return FoodSafetyLayer.from_cli(value)


def _limit(value: str) -> int:
    limit = int(value)
    if not 1 <= limit <= 2000:
        raise argparse.ArgumentTypeError("expected 1 through 2000")
    return limit


def _near_center(args: argparse.Namespace, api: FoodSafetyAPI) -> Geometry:
    if args.latitude is not None and args.longitude is not None:
        return Geometry(x=args.longitude, y=args.latitude)
    if args.latitude is not None or args.longitude is not None:
        raise FoodSafetyError("Use both --lat and --lon for coordinate searches.")

    address = _address(args.address)
    candidates = api.geocode(address, city=args.city, zip_code=args.zip_code, limit=1)
    if not candidates:
        raise FoodSafetyError(f"No King County geocode candidate found for '{address}'.")
    return candidates[0].location


def _rating(value: str) -> FoodSafetyRating:
    return FoodSafetyRating.from_cli(value)


def _spatial_filter(args: argparse.Namespace) -> SpatialFilter | None:
    if args.latitude is None and args.longitude is None:
        return None
    if args.latitude is None or args.longitude is None:
        raise FoodSafetyError("Use both --lat and --lon for spatial queries.")
    return SpatialFilter(latitude=args.latitude, longitude=args.longitude, radius_miles=args.radius)


if __name__ == "__main__":
    sys.exit(main())
