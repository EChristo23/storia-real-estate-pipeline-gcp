'''One-time backfill for listing_presence.last_seen.

PresenceLoader only ever looks at each property type's *latest* stage-1 scrape
date, so listings that went inactive before last_seen tracking began have no
row in listing_presence at all. This script reconstructs last_seen for those
by scanning every historical stage-1 date in GCS (not just the latest) and
taking, for each listing_id, the most recent date it appeared in that day's
listing_summary.json.

Existing last_seen values are never decreased (MERGE uses GREATEST), so this
is safe to run even though it re-scans dates PresenceLoader has already
processed.

Usage: uv run backfill_last_seen.py
'''

import json
import logging

from dotenv import load_dotenv
from google.cloud import bigquery, storage

from src import config
from src.standardization.schema import LISTING_PRESENCE_SCHEMA

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def all_dates(bucket: storage.Bucket, prop_type: str) -> list[str]:
    '''Returns every list-page scrape date recorded for a property type, ascending.'''
    iterator = bucket.list_blobs(prefix=f"{prop_type}/", delimiter="/")
    list(iterator)  # exhaust the iterator so .prefixes gets populated
    dates = [p.rstrip("/").split("/")[-1] for p in iterator.prefixes]
    return sorted(d for d in dates if d != "detail")


def read_listing_ids(bucket: storage.Bucket, prop_type: str, date: str) -> list[str]:
    '''Reads listing_summary.json for a property type/date and returns its listing IDs.'''
    blob = bucket.blob(f"{prop_type}/{date}/listing_summary.json")
    if not blob.exists():
        logger.warning(f"No listing_summary.json found for '{prop_type}' on {date}")
        return []
    summary = json.loads(blob.download_as_text())
    return list(summary.keys())


def main():
    cfg = config.load()
    storage_client = storage.Client()
    bucket = storage_client.bucket(cfg["gcs"]["raw_bucket"])
    bigquery_client = bigquery.Client()

    bq = cfg["bigquery"]
    table_name = f"{bq['project']}.{bq['dataset']}.{bq['listing_presence_table']}"

    seen: dict[str, str] = {}
    for prop_type in cfg["scraping"]["property_types"]:
        dates = all_dates(bucket, prop_type)
        logger.info(f"'{prop_type}': scanning {len(dates)} historical dates: {dates}")
        for date in dates:
            listing_ids = read_listing_ids(bucket, prop_type, date)
            for lid in listing_ids:
                seen[lid] = max(date, seen[lid]) if lid in seen else date
            logger.info(f"'{prop_type}' {date}: {len(listing_ids)} listings")

    if not seen:
        logger.warning("No historical listings found across any property type; nothing to backfill.")
        return

    rows = [{"listing_id": lid, "last_seen": date} for lid, date in seen.items()]
    logger.info(f"Reconstructed last_seen for {len(rows)} unique listings across all history.")

    staging_table = f"{table_name}_backfill_staging"
    load_job = bigquery_client.load_table_from_json(
        rows,
        staging_table,
        job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE",
            schema=LISTING_PRESENCE_SCHEMA,
        ),
    )
    load_job.result()

    bigquery_client.query(f'''
        MERGE `{table_name}` T
        USING `{staging_table}` S
        ON T.listing_id = S.listing_id
        WHEN MATCHED THEN UPDATE SET last_seen = GREATEST(T.last_seen, S.last_seen)
        WHEN NOT MATCHED THEN INSERT (listing_id, last_seen) VALUES (S.listing_id, S.last_seen)
    ''').result()

    bigquery_client.delete_table(staging_table, not_found_ok=True)
    logger.info(f"Backfill complete — merged {len(rows)} listings into listing_presence.")


if __name__ == "__main__":
    main()
