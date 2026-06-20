"""Helpers for raw ArcGIS payloads and snapshot records."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from king_county_food_safety.errors import FoodSafetyError


def payload_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return flat records from a raw ArcGIS query payload."""

    if "count" in payload:
        return [{"count": payload["count"]}]
    if "objectIds" in payload:
        return [{"object_id": object_id} for object_id in payload["objectIds"]]

    records: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        records.append(feature_record(feature))
    return records


def feature_record(feature: dict[str, Any]) -> dict[str, Any]:
    """Return a flat feature record with optional geometry fields."""

    attributes = feature.get("attributes", {})
    if not isinstance(attributes, dict):
        raise FoodSafetyError("ArcGIS feature did not include an attributes object.")

    record = dict(attributes)
    geometry = feature.get("geometry")
    if isinstance(geometry, dict):
        if "x" in geometry:
            record["geometry_x"] = geometry["x"]
        if "y" in geometry:
            record["geometry_y"] = geometry["y"]
        if "rings" in geometry:
            record["geometry_rings"] = geometry["rings"]
        if "paths" in geometry:
            record["geometry_paths"] = geometry["paths"]
    return record


def read_records(path: str) -> list[dict[str, Any]]:
    """Read records from a JSON array or JSON Lines file."""

    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped.startswith("["):
        value = json.loads(text)
        return [_ensure_record(item, path) for item in value]
    return [
        _ensure_record(json.loads(line), path)
        for line in text.splitlines()
        if line.strip()
    ]


def diff_records(
    old_records: Iterable[dict[str, Any]],
    new_records: Iterable[dict[str, Any]],
    *,
    key_field: str | None = None,
) -> list[dict[str, Any]]:
    """Return added, removed, and changed records between two snapshots."""

    old_records = list(old_records)
    new_records = list(new_records)
    selected_key = key_field or default_key_field([*old_records, *new_records])
    old_by_key = _record_map(old_records, selected_key)
    new_by_key = _record_map(new_records, selected_key)
    records: list[dict[str, Any]] = []

    for key in sorted(old_by_key.keys() - new_by_key.keys()):
        records.append(
            {
                "change": "removed",
                "key": key,
                "old": old_by_key[key],
                "new": None,
                "changed_fields": [],
            }
        )
    for key in sorted(new_by_key.keys() - old_by_key.keys()):
        records.append(
            {
                "change": "added",
                "key": key,
                "old": None,
                "new": new_by_key[key],
                "changed_fields": [],
            }
        )
    for key in sorted(old_by_key.keys() & new_by_key.keys()):
        old = old_by_key[key]
        new = new_by_key[key]
        changed_fields = sorted(
            field
            for field in old.keys() | new.keys()
            if old.get(field) != new.get(field)
        )
        if changed_fields:
            records.append(
                {
                    "change": "changed",
                    "key": key,
                    "old": old,
                    "new": new,
                    "changed_fields": changed_fields,
                }
            )
    return records


def compact_diff_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a flat diff record for delimited/table output."""

    changed_fields = record.get("changed_fields") or []
    return {
        "change": record.get("change"),
        "key": record.get("key"),
        "changed_fields": ",".join(changed_fields),
    }


def default_key_field(records: Iterable[dict[str, Any]]) -> str:
    """Choose a stable key field from snapshot records."""

    records = list(records)
    candidates = [
        "object_id",
        "OBJECTID",
        "business_record_id",
        "Business_Record_ID",
        "inspection_serial_number",
        "Inspection_Serial_Num",
    ]
    for candidate in candidates:
        if any(
            candidate in record and record[candidate] not in (None, "")
            for record in records
        ):
            return candidate
    raise FoodSafetyError("Could not infer a snapshot key. Use --key.")


def _ensure_record(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FoodSafetyError(f"Expected object records in {path}.")
    return value


def _record_map(
    records: Iterable[dict[str, Any]], key_field: str
) -> dict[str, dict[str, Any]]:
    records = list(records)
    mapped: dict[str, dict[str, Any]] = {}
    for record in records:
        try:
            key = record[key_field]
        except KeyError as error:
            raise FoodSafetyError(
                f"Record is missing key field '{key_field}'."
            ) from error
        key_text = str(key)
        if key_text in mapped:
            raise FoodSafetyError(
                f"Duplicate key '{key_text}' for field '{key_field}'."
            )
        mapped[key_text] = record
    return mapped
