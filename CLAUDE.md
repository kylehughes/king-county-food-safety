# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Tests use the stdlib `unittest` runner (no pytest dependency) and require `PYTHONPATH=src`. `uv` manages the env and lockfile; setuptools is the build backend.

```sh
# Run all tests
PYTHONPATH=src python3 -m unittest discover -s tests

# Run a single module / case / method (tests are flat top-level modules, not a package)
PYTHONPATH=src python3 -m unittest tests.test_cli
PYTHONPATH=src python3 -m unittest tests.test_api.SomeCase.test_method

# Tests with 100% coverage enforced (the project's only quality gate)
uv run --no-project --with coverage env PYTHONPATH=src \
  coverage run --source=src/king_county_food_safety -m unittest discover -s tests
uv run --no-project --with coverage coverage report --fail-under=100

# Lint, format, and type-check (all gated in CI)
uv run --no-project --with ruff ruff check .
uv run --no-project --with ruff ruff format .
uv run --no-project --with mypy mypy --strict src/king_county_food_safety

# Run the CLI (any of these)
PYTHONPATH=src python3 -m king_county_food_safety ratings
uv run king-county-food-safety ratings
```

Quality gates (enforced in CI on push to `main` and PRs): `ruff` lint + format, `mypy --strict` on `src/king_county_food_safety`, and 100% coverage — new code needs corresponding tests or coverage fails. Record types decode via a `SupportsFromArcGIS` protocol in `arcgis.py`; `ArcGISClient.query`/`query_all` are generic over a `RecordT` bound to it, so `query(q, FacilityRecord)` returns `list[Feature[FacilityRecord]]`. The `dev` extra (`pip install ".[dev]"`) installs `build`, `coverage`, `mypy`, `ruff`.

**Releasing:** bump `version` in `pyproject.toml`, commit, then push a matching `vX.Y.Z` tag. `release.yml` verifies tag == version, runs the coverage gate, builds, publishes to PyPI (trusted publishing, `pypi` environment), and creates the GitHub release. Follows semver — the CLI contract (commands, flags, output formats, exit codes, sorted JSON) is stable across minor/patch.

## Architecture

A zero-dependency (stdlib-only) CLI that reads King County's public food-safety ArcGIS REST services (facilities, inspections, violations) plus the county geocoder. No API key, no caching; all requests are `urllib` GETs with `f=json`. Endpoint URLs live in `constants.py`.

Strictly layered — dependencies point downward only:

```
cli.py        argparse UI, one handler per subcommand, I/O, manifests, input batching
  ├─ formatting.py   typed records -> flat display dicts; emit table/csv/tsv/json/jsonl
  ├─ raw.py          flatten untyped ArcGIS payloads; snapshot read + diff
  └─ api.py          FoodSafetyAPI: typed domain ops, builds WHERE clauses, batching, ID logic
       └─ arcgis.py  ArcGISClient + FeatureQuery: HTTP, JSON decode, paging, URL building
            ├─ models.py     frozen/slotted dataclasses + enums with from_arcgis decoders
            ├─ sql.py        SQL predicate builders (the injection-safe quoting layer)
            └─ errors.py     exception hierarchy
```

`main()` (cli.py) builds the `ArcGISClient` + `FoodSafetyAPI`, then dispatches via `args.handler(args, api)` set by each subcommand's `set_defaults`.

### Two parallel pipelines (important)

- **Typed commands** (`search`, `facility`, `inspections`, `violations`, `ratings`, `near`, `geocode`, `count`, `metadata`) go through `FoodSafetyAPI` returning typed `Feature[...]` objects, projected to display dicts by `formatting.py`.
- **Raw commands** (`query`, `export`, `snapshot`, `diff`) bypass the typed models entirely, calling `api.client.query_payload` / `query_all_payload` and flattening via `raw.payload_records`. This is why raw commands can surface arbitrary ArcGIS fields the dataclasses don't model.

### Conventions that span files

- **SQL safety is centralized.** All literal interpolation goes through `sql.py` (`string_literal` escapes quotes); field names are treated as trusted. Build WHERE clauses with `sql.and_`/`or_`/`contains`/`in_list`, never f-strings. Tests assert exact clause strings.
- **Error model.** Expected, user-facing failures are `FoodSafetyError` subclasses (`ArcGISError`, `HTTPStatusError`, `NetworkError`). `cli.main` catches `FoodSafetyError` and prints a one-line stderr message with exit 1 — unless `--verbose`, which re-raises the full traceback. Raise `FoodSafetyError` for handler-level validation; use argparse `type=` validators for argument-level checks.
- **Decode boundary.** ArcGIS CamelCase → snake_case mapping happens only in `from_arcgis` classmethods in `models.py`. (Note: the upstream `Businesss_Location_Long` triple-s typo is intentional — match the source field name.)
- **ID disambiguation.** A numeric facility ID may be an `OBJECTID` or a `Business_Record_ID`; `api.py` resolves both and batches IN-clauses (`DEFAULT_BATCH_SIZE = 75`).
- **"Public" filtering** (`PUBLIC_INSPECTION_CLAUSE`, active-facility default) replicates the county map's default filters; `--all` / `--include-inactive` opt out. This is a semantic choice, not a technical one.
- **Upstream schema can drift.** Field names and public-filter rules are owned by King County's map and can change when they update it. Empty results or a decode failure may mean the source schema moved, not a local bug — check `constants.py` endpoints and the `from_arcgis` decoders in `models.py`.
- **Deterministic output:** JSON uses `sort_keys=True`; floats are trimmed in delimited output.

## Testing patterns

- One `test_*.py` per source module. Tests assert on constructed WHERE clauses and `FeatureQuery` shape, not just results.
- **Fakes at the seams:** `test_api.py` uses a hand-written `FakeClient`; `test_cli.py` patches `king_county_food_safety.cli.FoodSafetyAPI` with a `FakeAPI`. `test_arcgis.py` patches `arcgis.urlopen` and subclasses `ArcGISClient` to test paging/retries.
- Output tests capture stdout via `redirect_stdout` and assert exact CSV/TSV/JSONL bytes.
- CLI error tests assert `SystemExit(1)` with no `Traceback` in stderr.
