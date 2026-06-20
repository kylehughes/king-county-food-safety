"""Command-line interface for King County food safety."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from king_county_food_safety import __version__
from king_county_food_safety.api import FoodSafetyAPI
from king_county_food_safety.arcgis import ArcGISClient, FeatureQuery, SpatialFilter
from king_county_food_safety.errors import FoodSafetyError
from king_county_food_safety.formatting import (
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
    rating_summary_record,
    violation_record,
)
from king_county_food_safety.models import (
    FacilityDetail,
    FoodSafetyLayer,
    FoodSafetyRating,
    Geometry,
    InspectionWithViolations,
    NearbyFacility,
    miles_between,
)
from king_county_food_safety.raw import (
    compact_diff_record,
    diff_records,
    payload_records,
    read_records,
)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        client = ArcGISClient(timeout=args.timeout, retries=args.retries)
        args.handler(args, FoodSafetyAPI(client=client))
    except FoodSafetyError as error:
        if args.verbose:
            raise
        parser.exit(1, f"{error}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the root argument parser."""

    parser = argparse.ArgumentParser(
        prog="king-county-food-safety",
        description="King County food safety ratings, inspections, violations, geocoding, and ArcGIS queries.",
    )
    parser.add_argument(
        "--retries",
        type=_nonnegative_int,
        default=0,
        help="Retry failed network requests this many times.",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=30.0,
        help="Network timeout in seconds.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show tracebacks for expected CLI/API failures.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    output_parent = argparse.ArgumentParser(add_help=False)
    output_group = output_parent.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="output_format",
        help="Print JSON.",
    )
    output_group.add_argument(
        "--jsonl",
        action="store_const",
        const="jsonl",
        dest="output_format",
        help="Print JSON Lines.",
    )
    output_group.add_argument(
        "--csv",
        action="store_const",
        const="csv",
        dest="output_format",
        help="Print CSV.",
    )
    output_group.add_argument(
        "--tsv",
        action="store_const",
        const="tsv",
        dest="output_format",
        help="Print TSV.",
    )
    output_parent.add_argument(
        "--fields",
        type=_fields,
        help="Comma-separated output fields. Use '*' for all fields.",
    )
    output_parent.set_defaults(output_format="table")

    search = subparsers.add_parser(
        "search", parents=[output_parent], help="Search food facilities."
    )
    search.add_argument("text", nargs="*", help="Name, address, city, or ZIP text.")
    search.add_argument("--city", help="Filter by city.")
    search.add_argument(
        "--establishment-type", help="Filter by establishment description text."
    )
    search.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive facility records.",
    )
    search.add_argument(
        "--limit", type=_limit, default=25, help="Limit records, 1 through 2000."
    )
    search.add_argument("--offset", type=int, default=0, help="ArcGIS result offset.")
    search.add_argument("--rating", type=_rating, help="Filter by rating.")
    search.add_argument("--status", help="Filter by exact business status.")
    search.add_argument(
        "--updated-since",
        type=_date,
        help="Filter by Load_DT_TM on or after YYYY-MM-DD.",
    )
    search.add_argument("--zip", dest="zip_code", help="Filter by ZIP.")
    search.set_defaults(handler=_search)

    facility = subparsers.add_parser(
        "facility", aliases=["get"], parents=[output_parent], help="Show one facility."
    )
    facility.add_argument(
        "facility_id", nargs="?", help="Business_Record_ID or OBJECTID."
    )
    facility.add_argument(
        "--all-inspections",
        action="store_true",
        help="Include non-public inspection rows.",
    )
    facility.add_argument(
        "--include-inactive",
        action="store_true",
        help="Allow inactive facility records.",
    )
    facility.add_argument(
        "--input-file", help="Read facility IDs from a newline-delimited file."
    )
    facility.add_argument(
        "--limit", type=_limit, default=10, help="Inspection limit when included."
    )
    facility.add_argument(
        "--stdin",
        action="store_true",
        help="Read facility IDs from stdin, one per line.",
    )
    facility.add_argument(
        "--with-inspections", action="store_true", help="Include inspection history."
    )
    facility.add_argument(
        "--with-violations",
        action="store_true",
        help="Include violations for included inspections.",
    )
    facility.set_defaults(handler=_facility)

    inspections = subparsers.add_parser(
        "inspections",
        aliases=["history"],
        parents=[output_parent],
        help="Show inspection history.",
    )
    inspections.add_argument(
        "facility_id", nargs="?", help="Business_Record_ID or OBJECTID."
    )
    inspections.add_argument(
        "--all",
        action="store_true",
        dest="include_non_public",
        help="Include non-public rows.",
    )
    inspections.add_argument(
        "--date-from", type=_date, help="Filter inspection date on or after YYYY-MM-DD."
    )
    inspections.add_argument(
        "--date-to", type=_date, help="Filter inspection date on or before YYYY-MM-DD."
    )
    inspections.add_argument(
        "--include-inactive",
        action="store_true",
        help="Allow inactive facility records.",
    )
    inspections.add_argument(
        "--input-file", help="Read facility IDs from a newline-delimited file."
    )
    inspections.add_argument(
        "--limit", type=_limit, default=25, help="Limit inspection records."
    )
    inspections.add_argument("--result", help="Filter exact inspection result.")
    inspections.add_argument(
        "--score-max", type=int, help="Filter inspection score at or below this value."
    )
    inspections.add_argument(
        "--score-min", type=int, help="Filter inspection score at or above this value."
    )
    inspections.add_argument(
        "--stdin",
        action="store_true",
        help="Read facility IDs from stdin, one per line.",
    )
    inspections.add_argument(
        "--updated-since",
        type=_date,
        help="Filter by Load_DT_TM on or after YYYY-MM-DD.",
    )
    inspections.add_argument(
        "--with-violations", action="store_true", help="Include violation rows."
    )
    inspections.set_defaults(handler=_inspections)

    violations = subparsers.add_parser(
        "violations", parents=[output_parent], help="Show inspection violations."
    )
    violations.add_argument(
        "inspection_serial_number", nargs="?", help="Inspection_Serial_Num."
    )
    violations.add_argument("--description", help="Filter violation description text.")
    violations.add_argument(
        "--input-file",
        help="Read inspection serial numbers from a newline-delimited file.",
    )
    violations.add_argument(
        "--points-max", type=int, help="Filter violation points at or below this value."
    )
    violations.add_argument(
        "--points-min", type=int, help="Filter violation points at or above this value."
    )
    violations.add_argument(
        "--stdin",
        action="store_true",
        help="Read inspection serial numbers from stdin, one per line.",
    )
    violations.add_argument(
        "--type",
        dest="violation_type",
        help="Filter violation type, such as RED or BLUE.",
    )
    violations.set_defaults(handler=_violations)

    ratings = subparsers.add_parser(
        "ratings",
        aliases=["summary"],
        parents=[output_parent],
        help="Summarize ratings.",
    )
    ratings.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive facility records.",
    )
    ratings.set_defaults(handler=_ratings)

    near = subparsers.add_parser(
        "near",
        aliases=["nearby"],
        parents=[output_parent],
        help="Find nearby facilities.",
    )
    near.add_argument("address", nargs="*", help="Address to geocode.")
    near.add_argument("--city", help="City hint for address geocoding.")
    near.add_argument(
        "--establishment-type", help="Filter by establishment description text."
    )
    near.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive facility records.",
    )
    near.add_argument(
        "--lat",
        "--latitude",
        dest="latitude",
        type=float,
        help="Search center latitude.",
    )
    near.add_argument(
        "--limit", type=_limit, default=25, help="Limit displayed records."
    )
    near.add_argument(
        "--lon",
        "--longitude",
        dest="longitude",
        type=float,
        help="Search center longitude.",
    )
    near.add_argument(
        "--radius", type=float, default=0.5, help="Radius in statute miles."
    )
    near.add_argument("--rating", type=_rating, help="Filter by rating.")
    near.add_argument("--status", help="Filter by exact business status.")
    near.add_argument(
        "--updated-since",
        type=_date,
        help="Filter by Load_DT_TM on or after YYYY-MM-DD.",
    )
    near.add_argument("--zip", dest="zip_code", help="ZIP hint for address geocoding.")
    near.set_defaults(handler=_near)

    geocode = subparsers.add_parser(
        "geocode", parents=[output_parent], help="Geocode a King County address."
    )
    geocode.add_argument("address", nargs="*", help="Address text.")
    geocode.add_argument("--city", help="City hint.")
    geocode.add_argument(
        "--limit", type=_limit, default=5, help="Limit geocoder candidates."
    )
    geocode.add_argument("--zip", dest="zip_code", help="ZIP hint.")
    geocode.set_defaults(handler=_geocode)

    count = subparsers.add_parser(
        "count", parents=[output_parent], help="Count records in a layer."
    )
    count.add_argument(
        "layer", type=_layer, help="facilities, inspections, violations, or search."
    )
    count.add_argument(
        "--where", dest="where_clause", default="1=1", help="ArcGIS SQL predicate."
    )
    count.set_defaults(handler=_count)

    metadata = subparsers.add_parser(
        "metadata",
        aliases=["schema"],
        parents=[output_parent],
        help="Show layer metadata.",
    )
    metadata.add_argument("layer", nargs="?", type=_layer, help="Layer to inspect.")
    metadata.set_defaults(handler=_metadata)

    query = subparsers.add_parser(
        "query", aliases=["raw"], help="Run a raw ArcGIS feature-layer query."
    )
    query.add_argument(
        "layer", type=_layer, help="facilities, inspections, violations, or search."
    )
    _add_raw_output_arguments(query)
    query.add_argument("--all", action="store_true", help="Fetch all result pages.")
    query.add_argument("--count", action="store_true", help="Return count only.")
    query.add_argument("--fields", dest="out_fields", help="Alias for --out-fields.")
    query.add_argument("--geometry", action="store_true", help="Return geometry.")
    query.add_argument(
        "--group-by",
        type=_comma_fields,
        help="Comma-separated ArcGIS groupByFieldsForStatistics.",
    )
    query.add_argument("--ids", action="store_true", help="Return object IDs only.")
    query.add_argument(
        "--lat",
        "--latitude",
        dest="latitude",
        type=float,
        help="Spatial query center latitude.",
    )
    query.add_argument(
        "--limit",
        type=_positive_int,
        help="Result limit for one page, or total cap with --all.",
    )
    query.add_argument(
        "--lon",
        "--longitude",
        dest="longitude",
        type=float,
        help="Spatial query center longitude.",
    )
    query.add_argument(
        "--manifest", help="Write query provenance and counts to this JSON file."
    )
    query.add_argument("--offset", type=int, help="ArcGIS resultOffset.")
    query.add_argument(
        "--order-by", dest="order_by", help="ArcGIS orderByFields value."
    )
    query.add_argument(
        "--out-fields", default="*", help="Comma-separated ArcGIS outFields value."
    )
    query.add_argument(
        "--page-size",
        type=_limit,
        default=2000,
        help="Page size for --all, 1 through 2000.",
    )
    query.add_argument(
        "--radius", type=float, default=0.5, help="Spatial query radius."
    )
    query.add_argument(
        "--resume-offset", type=int, help="Start offset for resumable --all exports."
    )
    query.add_argument(
        "--stat",
        action="append",
        default=[],
        type=_stat,
        help="ArcGIS statistic as type:field:alias.",
    )
    query.add_argument(
        "--where", dest="where_clause", default="1=1", help="ArcGIS SQL predicate."
    )
    query.set_defaults(handler=_query)

    export = subparsers.add_parser(
        "export",
        parents=[output_parent],
        help="Export a full ArcGIS layer as flat records.",
    )
    export.add_argument(
        "layer", type=_layer, help="facilities, inspections, violations, or search."
    )
    export.add_argument(
        "--geometry", action="store_true", help="Return geometry fields."
    )
    export.add_argument(
        "--group-by",
        type=_comma_fields,
        help="Comma-separated ArcGIS groupByFieldsForStatistics.",
    )
    export.add_argument(
        "--limit", type=_positive_int, help="Optional total record cap."
    )
    export.add_argument(
        "--manifest", help="Write export provenance and counts to this JSON file."
    )
    export.add_argument("--offset", type=int, help="ArcGIS resultOffset.")
    export.add_argument(
        "--order-by", dest="order_by", help="ArcGIS orderByFields value."
    )
    export.add_argument(
        "--out-fields", default="*", help="Comma-separated ArcGIS outFields value."
    )
    export.add_argument(
        "--page-size", type=_limit, default=2000, help="Page size, 1 through 2000."
    )
    export.add_argument(
        "--resume-offset", type=int, help="Start offset for resumable exports."
    )
    export.add_argument(
        "--stat",
        action="append",
        default=[],
        type=_stat,
        help="ArcGIS statistic as type:field:alias.",
    )
    export.add_argument(
        "--where", dest="where_clause", default="1=1", help="ArcGIS SQL predicate."
    )
    export.set_defaults(handler=_export)

    snapshot = subparsers.add_parser(
        "snapshot", help="Write a JSONL snapshot for a layer."
    )
    snapshot.add_argument(
        "layer", type=_layer, help="facilities, inspections, violations, or search."
    )
    snapshot.add_argument(
        "--geometry", action="store_true", help="Return geometry fields."
    )
    snapshot.add_argument(
        "--limit", type=_positive_int, help="Optional total record cap."
    )
    snapshot.add_argument(
        "--manifest", help="Write snapshot provenance to this JSON file."
    )
    snapshot.add_argument(
        "--order-by", dest="order_by", help="ArcGIS orderByFields value."
    )
    snapshot.add_argument(
        "--out-fields", default="*", help="Comma-separated ArcGIS outFields value."
    )
    snapshot.add_argument(
        "--output", required=True, help="Snapshot JSONL output file, or '-' for stdout."
    )
    snapshot.add_argument(
        "--page-size", type=_limit, default=2000, help="Page size, 1 through 2000."
    )
    snapshot.add_argument(
        "--where", dest="where_clause", default="1=1", help="ArcGIS SQL predicate."
    )
    snapshot.set_defaults(handler=_snapshot)

    diff = subparsers.add_parser(
        "diff", parents=[output_parent], help="Diff two JSONL or JSON snapshot files."
    )
    diff.add_argument("old_snapshot", help="Old JSONL or JSON snapshot file.")
    diff.add_argument("new_snapshot", help="New JSONL or JSON snapshot file.")
    diff.add_argument("--key", help="Record key field. Defaults to common ID fields.")
    diff.set_defaults(handler=_diff)

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
    facility_ids = _input_values(
        args.facility_id,
        use_stdin=args.stdin,
        input_file=args.input_file,
        name="facility id",
    )
    if len(facility_ids) > 1:
        if args.with_inspections or args.with_violations:
            raise FoodSafetyError(
                "--with-inspections and --with-violations are only supported for one facility."
            )
        facilities = api.facilities_for_ids(
            facility_ids, include_inactive=args.include_inactive
        )
        emit_records(
            [facility_record(facility) for facility in facilities],
            output_format=args.output_format,
            default_fields=FACILITY_FIELDS,
            fields=args.fields,
        )
        return

    facility = api.facility(facility_ids[0], include_inactive=args.include_inactive)
    include_inspections = args.with_inspections or args.with_violations
    details = None
    if include_inspections:
        inspections = api.inspections(
            facility_ids[0],
            include_non_public=args.all_inspections,
            include_inactive_facility=args.include_inactive,
            limit=args.limit,
        )
        details = _inspection_details(
            api, inspections, include_violations=args.with_violations
        )
    print_facility_detail(
        FacilityDetail(facility=facility, inspections=details),
        output_format=args.output_format,
        fields=args.fields,
    )


def _geocode(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    address = _address(args.address)
    candidates = api.geocode(
        address, city=args.city, zip_code=args.zip_code, limit=args.limit
    )
    emit_records(
        [geocode_record(candidate) for candidate in candidates],
        output_format=args.output_format,
        default_fields=GEOCODE_FIELDS,
        fields=args.fields,
    )


def _inspections(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    _validate_numeric_range(args.score_min, args.score_max, name="score")
    facility_ids = _input_values(
        args.facility_id,
        use_stdin=args.stdin,
        input_file=args.input_file,
        name="facility id",
    )
    if args.stdin or args.input_file or len(facility_ids) > 1:
        inspections = api.inspections_for_facility_ids(
            facility_ids,
            date_from=args.date_from,
            date_to=args.date_to,
            include_non_public=args.include_non_public,
            include_inactive_facility=args.include_inactive,
            limit_per_facility=args.limit,
            result=args.result,
            score_max=args.score_max,
            score_min=args.score_min,
            updated_since=args.updated_since,
        )
    else:
        inspections = api.inspections(
            facility_ids[0],
            date_from=args.date_from,
            date_to=args.date_to,
            include_non_public=args.include_non_public,
            include_inactive_facility=args.include_inactive,
            limit=args.limit,
            result=args.result,
            score_max=args.score_max,
            score_min=args.score_min,
            updated_since=args.updated_since,
        )
    if args.with_violations:
        emit_records(
            inspection_violation_records(
                _inspection_details(api, inspections, include_violations=True)
            ),
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
        establishment_type=args.establishment_type,
        status=args.status,
        updated_since=args.updated_since,
    )
    nearby = sorted(
        [
            NearbyFacility(
                distance_miles=miles_between(center, facility.geometry)
                if facility.geometry
                else float("inf"),
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
    query = _feature_query_from_args(args)
    payload = (
        api.client.query_all_payload(
            query, page_size=args.page_size, record_limit=args.limit
        )
        if args.all
        else api.client.query_payload(query)
    )
    _write_manifest(
        args.manifest, payload, query=query, page_size=args.page_size, command="query"
    )
    if args.output_format == "raw-json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    records = payload_records(payload)
    emit_records(
        records,
        output_format=args.output_format,
        default_fields=_record_fields(records, payload),
    )


def _export(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    query = _feature_query_from_args(args)
    payload = api.client.query_all_payload(
        query, page_size=args.page_size, record_limit=args.limit
    )
    _write_manifest(
        args.manifest, payload, query=query, page_size=args.page_size, command="export"
    )
    records = payload_records(payload)
    output_format = "jsonl" if args.output_format == "table" else args.output_format
    emit_records(
        records,
        output_format=output_format,
        default_fields=_record_fields(records, payload),
        fields=args.fields,
    )


def _snapshot(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    query = _feature_query_from_args(args)
    payload = api.client.query_all_payload(
        query, page_size=args.page_size, record_limit=args.limit
    )
    records = payload_records(payload)
    _write_jsonl(args.output, records)
    manifest_path = args.manifest
    if manifest_path is None and args.output != "-":
        manifest_path = f"{args.output}.manifest.json"
    _write_manifest(
        manifest_path,
        payload,
        query=query,
        page_size=args.page_size,
        command="snapshot",
    )


def _diff(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    del api
    records = diff_records(
        read_records(args.old_snapshot),
        read_records(args.new_snapshot),
        key_field=args.key,
    )
    if args.output_format in {"csv", "table", "tsv"}:
        emit_records(
            [compact_diff_record(record) for record in records],
            output_format=args.output_format,
            default_fields=["change", "key", "changed_fields"],
            fields=args.fields,
        )
        return
    emit_records(
        records,
        output_format=args.output_format,
        default_fields=["change", "key", "changed_fields", "old", "new"],
        fields=args.fields,
    )


def _ratings(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    emit_records(
        [
            rating_summary_record(summary)
            for summary in api.rating_summary(include_inactive=args.include_inactive)
        ],
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
        establishment_type=args.establishment_type,
        status=args.status,
        updated_since=args.updated_since,
    )
    emit_records(
        [facility_record(facility) for facility in facilities],
        output_format=args.output_format,
        default_fields=FACILITY_FIELDS,
        fields=args.fields,
    )


def _violations(args: argparse.Namespace, api: FoodSafetyAPI) -> None:
    _validate_numeric_range(args.points_min, args.points_max, name="points")
    serials = _input_values(
        args.inspection_serial_number,
        use_stdin=args.stdin,
        input_file=args.input_file,
        name="inspection serial number",
    )
    violations = (
        api.violations_for_inspection_serial_numbers(
            serials,
            description=args.description,
            points_max=args.points_max,
            points_min=args.points_min,
            violation_type=args.violation_type,
        )
        if args.stdin or args.input_file
        else api.violations(
            serials[0],
            description=args.description,
            points_max=args.points_max,
            points_min=args.points_min,
            violation_type=args.violation_type,
        )
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


def _add_raw_output_arguments(parser: argparse.ArgumentParser) -> None:
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="output_format",
        help="Print flat JSON records.",
    )
    output_group.add_argument(
        "--jsonl",
        action="store_const",
        const="jsonl",
        dest="output_format",
        help="Print flat JSON Lines records.",
    )
    output_group.add_argument(
        "--csv",
        action="store_const",
        const="csv",
        dest="output_format",
        help="Print flat CSV records.",
    )
    output_group.add_argument(
        "--tsv",
        action="store_const",
        const="tsv",
        dest="output_format",
        help="Print flat TSV records.",
    )
    parser.set_defaults(output_format="raw-json")


def _comma_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _comma_fields(value: str) -> list[str]:
    fields = _comma_list(value)
    if not fields:
        raise argparse.ArgumentTypeError("expected at least one field")
    return fields


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from error


def _fields(value: str) -> list[str]:
    fields = _comma_list(value)
    if not fields:
        raise argparse.ArgumentTypeError("expected at least one field")
    return fields


def _feature_query_from_args(args: argparse.Namespace) -> FeatureQuery:
    if getattr(args, "count", False) and getattr(args, "ids", False):
        raise FoodSafetyError("Use either --count or --ids, not both.")
    if getattr(args, "group_by", None) and not getattr(args, "stat", []):
        raise FoodSafetyError("Use --stat with --group-by.")
    offset = _resolved_offset(
        getattr(args, "offset", None), getattr(args, "resume_offset", None)
    )
    return FeatureQuery(
        layer=args.layer,
        where_clause=args.where_clause,
        fields=tuple(_comma_list(getattr(args, "out_fields", "*"))) or ("*",),
        return_geometry=args.geometry,
        order_by_fields=tuple(_comma_list(args.order_by)),
        limit=None if getattr(args, "all", True) else getattr(args, "limit", None),
        offset=offset,
        spatial_filter=_spatial_filter(args),
        group_by_fields_for_statistics=tuple(getattr(args, "group_by", None) or ()),
        out_statistics=_statistics(getattr(args, "stat", [])),
        return_count_only=getattr(args, "count", False),
        return_ids_only=getattr(args, "ids", False),
    )


def _input_values(
    value: str | None,
    *,
    use_stdin: bool,
    input_file: str | None = None,
    name: str,
) -> list[str]:
    values: list[str] = []
    if input_file:
        values.extend(
            line.strip()
            for line in Path(input_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
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


def _manifest(
    payload: dict[str, Any], *, query: FeatureQuery, page_size: int, command: str
) -> dict[str, Any]:
    records = payload_records(payload)
    return {
        "command": command,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "layer": query.layer.value,
        "record_count": len(records),
        "request_url": query.url(),
        "schema_fields": [
            field.get("name")
            for field in payload.get("fields", [])
            if isinstance(field, dict)
        ],
        "tool": "king-county-food-safety",
        "tool_version": __version__,
        "query": {
            "group_by": list(query.group_by_fields_for_statistics),
            "offset": query.offset,
            "order_by": list(query.order_by_fields),
            "out_fields": list(query.fields),
            "out_statistics": json.loads(query.out_statistics)
            if query.out_statistics
            else None,
            "page_size": page_size,
            "return_count_only": query.return_count_only,
            "return_geometry": query.return_geometry,
            "return_ids_only": query.return_ids_only,
            "where": query.where_clause,
        },
    }


def _record_fields(
    records: list[dict[str, Any]], payload: dict[str, Any] | None = None
) -> list[str]:
    fields: list[str] = []
    for field in (payload or {}).get("fields", []):
        if not isinstance(field, dict):
            continue
        field_name = field.get("name")
        if isinstance(field_name, str) and field_name not in fields:
            fields.append(field_name)
    for record in records:
        for field in record:
            if field not in fields:
                fields.append(field)
    return fields


def _resolved_offset(offset: int | None, resume_offset: int | None) -> int | None:
    if offset is not None and resume_offset is not None and offset != resume_offset:
        raise FoodSafetyError("Use either --offset or --resume-offset, not both.")
    return resume_offset if resume_offset is not None else offset


def _stat(value: str) -> dict[str, str]:
    parts = value.split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError(
            "expected statisticType:onStatisticField:outStatisticFieldName"
        )
    return {
        "statisticType": parts[0].strip(),
        "onStatisticField": parts[1].strip(),
        "outStatisticFieldName": parts[2].strip(),
    }


def _statistics(values: list[dict[str, str]]) -> str | None:
    if not values:
        return None
    return json.dumps(values, separators=(",", ":"))


def _validate_numeric_range(
    minimum: int | None, maximum: int | None, *, name: str
) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise FoodSafetyError(f"{name} minimum cannot be greater than {name} maximum.")


def _write_jsonl(path: str, records: list[dict[str, Any]]) -> None:
    lines = [json.dumps(record, sort_keys=True) for record in records]
    text = "\n".join(lines)
    if lines:
        text += "\n"
    if path == "-":
        print(text, end="")
        return
    Path(path).write_text(text, encoding="utf-8")


def _write_manifest(
    path: str | None,
    payload: dict[str, Any],
    *,
    query: FeatureQuery,
    page_size: int,
    command: str,
) -> None:
    if path is None:
        return
    Path(path).write_text(
        json.dumps(
            _manifest(payload, query=query, page_size=page_size, command=command),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _inspection_details(
    api: FoodSafetyAPI,
    inspections: list,
    *,
    include_violations: bool,
) -> list[InspectionWithViolations]:
    if not include_violations:
        return [
            InspectionWithViolations(inspection=inspection, violations=[])
            for inspection in inspections
        ]

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
        details.append(
            InspectionWithViolations(inspection=inspection, violations=violations)
        )
    return details


def _layer(value: str) -> FoodSafetyLayer:
    return FoodSafetyLayer.from_cli(value)


def _limit(value: str) -> int:
    limit = int(value)
    if not 1 <= limit <= 2000:
        raise argparse.ArgumentTypeError("expected 1 through 2000")
    return limit


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("expected at least 1")
    return number


def _nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("expected zero or greater")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("expected greater than zero")
    return number


def _near_center(args: argparse.Namespace, api: FoodSafetyAPI) -> Geometry:
    if args.latitude is not None and args.longitude is not None:
        return Geometry(x=args.longitude, y=args.latitude)
    if args.latitude is not None or args.longitude is not None:
        raise FoodSafetyError("Use both --lat and --lon for coordinate searches.")

    address = _address(args.address)
    candidates = api.geocode(address, city=args.city, zip_code=args.zip_code, limit=1)
    if not candidates:
        raise FoodSafetyError(
            f"No King County geocode candidate found for '{address}'."
        )
    return candidates[0].location


def _rating(value: str) -> FoodSafetyRating:
    return FoodSafetyRating.from_cli(value)


def _spatial_filter(args: argparse.Namespace) -> SpatialFilter | None:
    latitude = getattr(args, "latitude", None)
    longitude = getattr(args, "longitude", None)
    if latitude is None and longitude is None:
        return None
    if latitude is None or longitude is None:
        raise FoodSafetyError("Use both --lat and --lon for spatial queries.")
    return SpatialFilter(
        latitude=latitude, longitude=longitude, radius_miles=args.radius
    )


if __name__ == "__main__":
    sys.exit(main())
