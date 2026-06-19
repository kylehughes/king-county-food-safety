# King County Food Safety Ratings CLI

Python CLI for King County food facility ratings, inspection history, violations, address geocoding, and raw ArcGIS feature-layer queries.

## About

This package exposes the public ArcGIS services behind King County's food safety rating map as a local command-line tool named `king-county-food-safety`.

- Public page: <https://kingcounty.gov/en/dept/dph/health-safety/food-safety/search-restaurant-safety-ratings>
- ArcGIS Experience item: `d7adc44a99e8406fbf86bdaf0a856136`
- Food safety FeatureServer: <https://services.arcgis.com/Ej0PsM5Aw677QF1W/arcgis/rest/services/EPL_BusinessPoint/FeatureServer>
- King County geocoder: <https://gismaps.kingcounty.gov/arcgis/rest/services/Address/Composite_locator/GeocodeServer>

The CLI uses only the Python standard library at runtime and does not require an API key.

## Getting Started

Run from the repository without installing:

```sh
PYTHONPATH=src python3 -m king_county_food_safety ratings
```

Run the packaged console script through `uv`:

```sh
uv run king-county-food-safety ratings
```

Install the command into an active virtual environment:

```sh
uv pip install -e .
king-county-food-safety ratings
```

Run tests:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Common Commands

Search facilities:

```sh
king-county-food-safety search "dick's drive in" --limit 5
king-county-food-safety search --city Seattle --rating needs-to-improve
king-county-food-safety search "98105" --jsonl --fields business_record_id,business_name,rating
```

Show one facility:

```sh
king-county-food-safety facility PFE-PR-3126839
king-county-food-safety facility 2072 --with-inspections --with-violations
```

Show inspection history:

```sh
king-county-food-safety inspections PFE-PR-3126839 --limit 10
king-county-food-safety inspections PFE-PR-3126839 --with-violations --csv
```

Show violations for one inspection:

```sh
king-county-food-safety violations PFE-DABP9LQSH
```

Compose nearby facilities, inspections, and violations:

```sh
king-county-food-safety near "111 NE 45TH ST" --city Seattle --zip 98105 \
  --radius 0.5 \
  --jsonl \
  --fields business_record_id \
  | jq -r '.business_record_id' \
  | king-county-food-safety inspections --stdin --jsonl --fields inspection_serial_number \
  | jq -r '.inspection_serial_number' \
  | king-county-food-safety violations --stdin --jsonl
```

Find nearby facilities:

```sh
king-county-food-safety near "111 NE 45TH ST" --city Seattle --radius 0.25
king-county-food-safety near --lat 47.661115 --lon -122.327789 --radius 0.25 --tsv
```

Run a raw ArcGIS query:

```sh
king-county-food-safety query facilities \
  --where "Business_Grade = 'Needs to Improve'" \
  --fields Business_Record_ID,Business_Name,Business_Address,Business_City,Business_Grade \
  --limit 10
```

## Commands

| Command | Purpose |
| --- | --- |
| `search [text]` | Search food facilities by name, address, city, ZIP, and rating. |
| `facility <id>` | Show one facility by `Business_Record_ID` or `OBJECTID`. |
| `inspections <facility-id>` | Show inspection history for a facility. |
| `violations <serial>` | Show violations for an `Inspection_Serial_Num`. |
| `ratings` | Count facilities grouped by public safety rating. |
| `near [address]` | Find facilities near an address or coordinate. |
| `geocode <address>` | Geocode a King County address to WGS84 coordinates. |
| `count <layer>` | Count records in an ArcGIS layer. |
| `metadata [layer]` | Show layer URLs or layer field metadata. |
| `query <layer>` | Run a raw ArcGIS feature-layer query. |

Use `--help` on any command for exact options:

```sh
king-county-food-safety search --help
king-county-food-safety query --help
```

## Unix-Style Output

Typed commands support these output formats:

- default table output for humans
- `--json` for a JSON array
- `--jsonl` for one JSON object per line
- `--csv` for comma-separated records
- `--tsv` for tab-separated records

Use `--fields` to project flat normalized output fields:

```sh
king-county-food-safety near "111 NE 45TH ST" --city Seattle \
  --jsonl \
  --fields distance_miles,business_record_id,business_name,rating
```

Use `--fields '*'` to print every normalized field for a command:

```sh
king-county-food-safety inspections PFE-PR-3126839 --jsonl --fields '*'
```

`inspections --stdin` reads facility IDs from stdin. `violations --stdin` reads inspection serial numbers from stdin. Both commands batch those IDs into ArcGIS `IN (...)` queries internally, so shell pipelines avoid one network request per input row.

## Layers

| CLI layer | ArcGIS layer | Description |
| --- | --- | --- |
| `facilities` | `EPL_Business_XYTableToPoint` | Facility ratings, names, addresses, status, and point geometry. |
| `inspections` | `EPL_Inspection` | Inspection dates, scores, results, and serial numbers. |
| `violations` | `EPL_Violation` | Violation descriptions and points by inspection serial number. |
| `search` | `King County Restaurant Inspection and Violation Records SEARCH view` | Limited search view exposed by the public map. |

The public map filters inspection history to:

```sql
(Inspection_Type <> 'Consultation/Education')
AND (Inspection_Result IN ('Satisfactory','Unsatisfactory'))
```

The `inspections` command applies that filter by default. Use `--all` to inspect all rows returned by the API.

## Project Layout

```text
src/king_county_food_safety/
  api.py         typed King County operations
  arcgis.py      ArcGIS REST client and query builder
  cli.py         argparse command surface
  formatting.py  normalized records and output formats
  models.py      dataclass records and layer/rating enums
  sql.py         ArcGIS SQL escaping helpers
tests/           stdlib unittest coverage
```

## Constraints

The CLI depends on King County's public ArcGIS services. Field names, layer URLs, and public filtering rules can change when King County updates the map. Use `king-county-food-safety metadata <layer>` to inspect the current schema, and use `query` when the typed commands do not cover a new ArcGIS query shape.

The CLI does not cache responses. Every command reads current data from the public service.
