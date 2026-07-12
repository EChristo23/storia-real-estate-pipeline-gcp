# storia-real-estate-pipeline-gcp

An end-to-end Medallion architecture data pipeline that scrapes real estate listings from [Storia.ro](https://www.storia.ro) and loads them into Google BigQuery for analysis.

## Architecture

The pipeline follows a **Bronze → Silver → Gold** Medallion pattern:

| Layer | Status | Description |
|---|---|---|
| Bronze | In progress | Raw JSON pages ingested from Storia.ro into GCS |
| Silver | Planned | Cleaned and validated listings in BigQuery |
| Gold | Planned | Aggregated analytics models via dbt |

## Ingestion

**`Scrapper`** (`src/ingestion/scraper.py`)
Uses Storia.ro's Next.js `/_next/data/` endpoint to fetch paginated listing pages. Each page holds up to 72 listings. Scraped pages are written as JSON blobs to Google Cloud Storage under `{type}/{YYYY-MM-DD}/{YYYY-MM-DD}_{page}.json`.

## Tech Stack

- **Python 3.12+** managed with [`uv`](https://github.com/astral-sh/uv)
- **httpx** — async HTTP client with HTTP/2 support
- **BeautifulSoup + lxml** — HTML parsing for build ID extraction
- **asyncio** — concurrent page fetching
- **Google Cloud Storage** — Bronze layer landing zone
- **BigQuery** — target analytical store (planned)
- **Cloud Run** — deployment target (planned)
- **dbt** — transformation layer (planned)

## Configuration

All pipeline parameters live in `config/pipeline.toml`:

```toml
[scraping]
property_types = ["casa", "apartament"]   # property types to scrape
# n_pages = 10                            # optional page cap (omit for all)
raw_bucket = "raw_real_estate"            # GCS bucket name
```

Valid `property_types` values: `casa`, `apartament`, `teren`, `garsoniera`, `vila`.

## Setup

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env          # then fill in GOOGLE_APPLICATION_CREDENTIALS
```

`.env` variables:

| Variable | Description |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON key (not needed on Cloud Run) |
| `LOG_DIR` | Directory for local log files. Omit to disable file logging. |

## Running

```bash
uv run main.py
```

Logs are written as JSON to stdout (compatible with Cloud Logging). When `LOG_DIR` is set, plain-text logs are also written to `{LOG_DIR}/scraper.log` with daily rotation and 7-day retention.

## Project Structure

```
├── config/
│   └── pipeline.toml       # pipeline configuration
├── src/
│   ├── config.py           # TOML config loader
│   └── ingestion/
│       └── scraper.py      # Scrapper — paginated listing pages → GCS
├── main.py                 # entrypoint
└── pyproject.toml
```

## Deployment

Intended for Google Cloud Run. The container reads config from `pipeline.toml` and authenticates to GCP via the attached service account (no credential file needed).
