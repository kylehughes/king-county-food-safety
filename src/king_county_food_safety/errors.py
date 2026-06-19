"""Package-specific error types."""

from __future__ import annotations


class FoodSafetyError(Exception):
    """Base error for expected CLI/API failures."""


class ArcGISError(FoodSafetyError):
    """Error returned by an ArcGIS REST endpoint."""

    def __init__(self, code: int, message: str, details: list[str] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or []
        detail_suffix = f" ({'; '.join(self.details)})" if self.details else ""
        super().__init__(f"ArcGIS API error {code}: {message}{detail_suffix}")


class HTTPStatusError(FoodSafetyError):
    """Unexpected HTTP status from a public endpoint."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} from {url}")
        self.status_code = status_code
        self.url = url
