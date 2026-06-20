"""Small SQL helpers for ArcGIS query predicates."""

from __future__ import annotations

from datetime import date


def and_(*clauses: str | None) -> str:
    """Return a SQL `AND` expression for non-empty clauses."""

    non_empty = [clause.strip() for clause in clauses if clause and clause.strip()]
    if not non_empty:
        return "1=1"
    return " AND ".join(f"({clause})" for clause in non_empty)


def contains(field: str, value: str) -> str:
    """Return a case-insensitive contains predicate for a trusted field name."""

    return f"UPPER({field}) LIKE {string_literal(f'%{value.upper()}%')}"


def date_literal(value: date) -> str:
    """Return an ArcGIS SQL date-only literal."""

    return f"DATE {string_literal(value.isoformat())}"


def in_list(field: str, values: list[str]) -> str:
    """Return a SQL `IN` predicate for string values."""

    return f"{field} IN ({literal_list(values)})"


def literal_list(values: list[str]) -> str:
    """Return comma-separated SQL string literals."""

    return ",".join(string_literal(value) for value in values)


def or_(*clauses: str | None) -> str:
    """Return a SQL `OR` expression for non-empty clauses."""

    non_empty = [clause.strip() for clause in clauses if clause and clause.strip()]
    if not non_empty:
        return "1=0"
    return " OR ".join(f"({clause})" for clause in non_empty)


def string_literal(value: str) -> str:
    """Return a SQL string literal with embedded quotes escaped."""

    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def timestamp_literal(value: date) -> str:
    """Return an ArcGIS SQL timestamp literal at the start of a day."""

    return f"TIMESTAMP {string_literal(f'{value.isoformat()} 00:00:00')}"
