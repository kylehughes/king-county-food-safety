# King County Food Safety Ratings CLI

[![PyPI](https://img.shields.io/pypi/v/king-county-food-safety-ratings-cli)](https://pypi.org/project/king-county-food-safety-ratings-cli/)
[![Python Versions](https://img.shields.io/pypi/pyversions/king-county-food-safety-ratings-cli)](https://pypi.org/project/king-county-food-safety-ratings-cli/)
[![CI](https://github.com/kylehughes/king-county-food-safety-ratings-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/kylehughes/king-county-food-safety-ratings-cli/actions/workflows/ci.yml)

*Command-line access to King County food facility ratings, inspection history, violations, geocoding, and raw ArcGIS feature-layer queries.*

The command is `king-county-food-safety`. It reads King County's public ArcGIS services directly, needs no API key, and has no runtime dependencies outside the Python standard library.

## Start Here

Use Python 3.12 or newer.

### Install

Install from PyPI with the tool of your choice:

```sh
uv tool install king-county-food-safety-ratings-cli
```

```sh
pipx install king-county-food-safety-ratings-cli
```

```sh
pip install king-county-food-safety-ratings-cli
```

Any of these puts the `king-county-food-safety` command on your path.

### Run the Command

```sh
king-county-food-safety ratings
```

Run from a checkout without installing:

```sh
PYTHONPATH=src python3 -m king_county_food_safety ratings
```

Run the packaged console script through `uv` in a checkout:

```sh
uv run king-county-food-safety ratings
```

Network options are root-level flags. Put them before the subcommand:

```sh
king-county-food-safety --timeout 10 --retries 2 export facilities --jsonl
```

Expected network and API failures print one-line errors. Add `--verbose` before the subcommand to get a traceback.

```sh
king-county-food-safety --verbose search pizza
```

## Workflows

### Search Facilities

```sh
king-county-food-safety search "pho" --limit 5
king-county-food-safety search --city Seattle --rating needs-to-improve
king-county-food-safety search --establishment-type "Risk Category III" --status Active
king-county-food-safety search "98105" --jsonl --fields business_record_id,business_name,rating
```

### Inspect Facility History

Show one facility:

```sh
king-county-food-safety facility PFE-PR-3126839
king-county-food-safety facility 2072 --with-inspections --with-violations
```

Show inspection history:

```sh
king-county-food-safety inspections PFE-PR-3126839 --limit 10
king-county-food-safety inspections PFE-PR-3126839 --with-violations --csv
king-county-food-safety inspections PFE-PR-3126839 --date-from 2025-01-01 --score-min 10
```

Show violations for one inspection:

```sh
king-county-food-safety violations PFE-DABP9LQSH
king-county-food-safety violations PFE-DABP9LQSH --type RED --points-min 10
```

### Find Nearby Facilities

```sh
king-county-food-safety near "401 5TH AVE" --city Seattle --radius 0.25
king-county-food-safety near --lat 47.603832 --lon -122.330062 --radius 0.25 --tsv
```

### Shape Output

Typed commands default to tables for humans. Use a machine format when piping into other tools:

- `--json` prints a JSON array.
- `--jsonl` prints one JSON object per line.
- `--csv` prints comma-separated records.
- `--tsv` prints tab-separated records.

Use `--fields` to project flat output fields:

```sh
king-county-food-safety near "401 5TH AVE" --city Seattle \
  --jsonl \
  --fields distance_miles,business_record_id,business_name,rating
```

Use `--fields '*'` to print every normalized field for a typed command:

```sh
king-county-food-safety inspections PFE-PR-3126839 --jsonl --fields '*'
```

### Batch Input

`inspections --stdin` reads facility IDs from stdin. `violations --stdin` reads inspection serial numbers from stdin. Both commands batch rows into ArcGIS `IN (...)` queries, so pipelines avoid one request per input row.

```sh
king-county-food-safety near "401 5TH AVE" --city Seattle \
  --radius 0.5 \
  --jsonl \
  --fields business_record_id \
  | jq -r '.business_record_id' \
  | king-county-food-safety inspections --stdin --jsonl --fields inspection_serial_number \
  | jq -r '.inspection_serial_number' \
  | king-county-food-safety violations --stdin --jsonl
```

`facility`, `inspections`, and `violations` also accept `--input-file` with one ID per line:

```sh
king-county-food-safety facility --input-file watchlist.txt --jsonl
king-county-food-safety inspections --input-file watchlist.txt --limit 1 --jsonl
```

### Query and Export Raw Data

`query` is the escape hatch for ArcGIS filtering. By default it prints the raw ArcGIS JSON payload:

```sh
king-county-food-safety query facilities \
  --where "Business_Grade = 'Needs to Improve'" \
  --out-fields Business_Record_ID,Business_Name,Business_Address,Business_City,Business_Grade \
  --limit 10
```

Add a machine format to flatten ArcGIS features into records:

```sh
king-county-food-safety query facilities \
  --where "Business_Grade = 'Needs to Improve'" \
  --out-fields Business_Record_ID,Business_Name,Business_Grade \
  --jsonl
```

Use `query --all` or `export` to page through a result set:

```sh
king-county-food-safety export inspections \
  --where "Inspection_Result = 'Unsatisfactory'" \
  --out-fields Business_Record_ID,Inspection_Date,Inspection_Score,Inspection_Result \
  --jsonl \
  --manifest inspections.manifest.json > inspections.jsonl
```

Raw ArcGIS aggregations use `--group-by` and repeatable `--stat` values:

```sh
king-county-food-safety export facilities \
  --group-by Business_City,Business_Grade \
  --stat count:OBJECTID:count \
  --csv
```

`--stat` uses `statisticType:onStatisticField:outStatisticFieldName`.

### Snapshot and Diff Data

`snapshot` writes JSONL and, by default, a sidecar manifest. The manifest records when the data was fetched, which layer was queried, and which query parameters were used.

```sh
king-county-food-safety snapshot facilities --output snapshots/facilities.jsonl
```

`diff` compares two JSONL or JSON-array snapshots and emits `added`, `removed`, and `changed` records. It can infer common keys such as `OBJECTID`, `Business_Record_ID`, `business_record_id`, and `Inspection_Serial_Num`.

```sh
king-county-food-safety diff snapshots/facilities-old.jsonl snapshots/facilities.jsonl --key OBJECTID --jsonl
```

## Reference

### Command Reference

| Command | Purpose |
| --- | --- |
| `search [text]` | Search facilities. |
| `facility <id>` | Show one facility by `Business_Record_ID` or `OBJECTID`. |
| `inspections <facility-id>` | Show inspection history for a facility. |
| `violations <serial>` | Show violations for an `Inspection_Serial_Num`. |
| `ratings` | Count facilities grouped by public rating. |
| `near [address]` | Find facilities near an address or coordinate. |
| `geocode <address>` | Geocode a King County address to WGS84 coordinates. |
| `count <layer>` | Count records in an ArcGIS layer. |
| `metadata [layer]` | Show layer URLs or layer field metadata. |
| `query <layer>` | Run a raw ArcGIS feature-layer query. |
| `export <layer>` | Page through a layer and emit flat records. |
| `snapshot <layer>` | Write a JSONL layer snapshot and manifest. |
| `diff <old> <new>` | Diff two JSONL or JSON snapshots by stable key. |

Use `--help` on any command for exact options:

```sh
king-county-food-safety search --help
king-county-food-safety query --help
```

### Layer Reference

| Layer | Records |
| --- | --- |
| `facilities` | Facility ratings, names, addresses, status, and point geometry. |
| `inspections` | Inspection dates, scores, results, and serial numbers. |
| `violations` | Violation descriptions and points by inspection serial number. |
| `search` | Search-view records exposed by the public map. |

The `inspections` command matches the public map's default inspection-history filter. Use `--all` to inspect every row returned by the API.

### Limit Reference

- `--page-size` controls one ArcGIS request and must be between 1 and 2000.
- `query --limit` without `--all` is a single ArcGIS request limit and must be between 1 and 2000.
- `query --all --limit`, `export --limit`, and `snapshot --limit` are total record caps and can be larger than one page.

### Service Constraints

The CLI depends on King County's public food safety map: <https://kingcounty.gov/en/dept/dph/health-safety/food-safety/search-restaurant-safety-ratings>. Field names and public filtering rules can change when King County updates the map.

Use `king-county-food-safety metadata <layer>` to inspect the current schema. Use `query` when the typed commands do not cover the ArcGIS query shape you need.

The CLI does not cache responses. Every command reads current data from the public service.

### Stability and Versioning

This project follows [semantic versioning](https://semver.org). The public contract is the command-line interface: command and alias names, flags, output formats, exit codes, and the deterministic, sorted JSON shape. Breaking any of these requires a major version bump.

The data itself is owned by King County. Field names and public filtering rules can change when the county updates its map, and those upstream changes are not treated as breaking changes to this CLI. Use `metadata <layer>` to inspect the current schema and `query` for shapes the typed commands do not cover.

## Development

### Run Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

Run tests with 100% coverage enforced:

```sh
uv run --no-project --with coverage env PYTHONPATH=src \
  coverage run --source=src/king_county_food_safety -m unittest discover -s tests
uv run --no-project --with coverage coverage report --fail-under=100
```

### Lint and Format

```sh
uv run --no-project --with ruff ruff check .
uv run --no-project --with ruff ruff format .
```

The `dev` extra (`pip install ".[dev]"`) installs the full tooling set: `build`, `coverage`, `mypy`, and `ruff`.

### Releasing

Releases are automated through GitHub Actions. Bump `version` in `pyproject.toml`, commit, then push a matching tag:

```sh
git tag v1.2.3
git push origin v1.2.3
```

The release workflow verifies the tag matches the package version, runs the coverage gate, builds distributions, publishes to PyPI via trusted publishing, and creates the GitHub release.

## Contributions

King County Food Safety Ratings CLI is not accepting source contributions at this time. Bug reports will be considered.

## Author

[Kyle Hughes](https://kylehugh.es)

[![Bluesky][bluesky_image]][bluesky_url]  
[![LinkedIn][linkedin_image]][linkedin_url]  
[![Mastodon][mastodon_image]][mastodon_url]

[bluesky_image]: https://img.shields.io/badge/Bluesky-0285FF?logo=bluesky&logoColor=fff
[bluesky_url]: https://bsky.app/profile/kylehugh.es
[linkedin_image]: https://img.shields.io/badge/LinkedIn-0A66C2?logo=linkedin&logoColor=fff
[linkedin_url]: https://www.linkedin.com/in/kyle-hughes
[mastodon_image]: https://img.shields.io/mastodon/follow/109356914477272810?domain=https%3A%2F%2Fmister.computer&style=social
[mastodon_url]: https://mister.computer/@kyle

## Disclaimer

King County Food Safety Ratings CLI is an independent, unofficial project. It is not affiliated with, endorsed by, or sponsored by King County or Public Health — Seattle & King County. It reads publicly available data from King County's ArcGIS services and is provided "as is," without warranty of any kind. The "King County" name is used only to identify the source of the data.

## License

King County Food Safety Ratings CLI is available under the MIT license.

See `LICENSE` for details.
