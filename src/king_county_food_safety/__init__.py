"""King County food safety CLI package."""

from importlib.metadata import PackageNotFoundError, version

from king_county_food_safety.api import FoodSafetyAPI


def _resolve_version() -> str:
    try:
        return version("king-county-food-safety")
    except PackageNotFoundError:
        return "unknown"


__version__ = _resolve_version()

__all__ = ["FoodSafetyAPI", "__version__"]
