import json
import logging

from google.cloud import bigquery, storage

from src.standardization.schema import LISTING_PRESENCE_SCHEMA

logger = logging.getLogger(__name__)


class PresenceLoader:
    '''Upserts the listing_presence table from each property type's most recent
    stage-1 (list-page) scrape: last_seen advances to today for listings still
    present, and is left untouched for listings that stopped appearing.'''

    def __init__(self, config):
        self.config = config
        self.storage_client = None
        self.bigquery_client = None
        self.bucket = None

    def set_storage_client(self):
        self.storage_client = storage.Client()

    def set_bigquery_client(self):
        self.bigquery_client = bigquery.Client()

    def set_bucket(self):
        if self.storage_client is None:
            self.set_storage_client()
        self.bucket = self.storage_client.bucket(self.config['gcs']['raw_bucket'])

    def _latest_date(self, prop_type: str) -> str | None:
        '''Returns the most recent list-page scrape date for a property type, or None if none exist.'''
        iterator = self.bucket.list_blobs(prefix=f"{prop_type}/", delimiter="/")
        list(iterator)  # exhaust the iterator so .prefixes gets populated
        dates = [p.rstrip("/").split("/")[-1] for p in iterator.prefixes]
        dates = [d for d in dates if d != "detail"]
        return max(dates) if dates else None

    def _read_listing_ids(self, prop_type: str, date: str) -> list[str]:
        '''Reads listing_summary.json for a property type/date and returns its listing IDs.'''
        blob = self.bucket.blob(f"{prop_type}/{date}/listing_summary.json")
        if not blob.exists():
            logger.warning(f"No listing_summary.json found for '{prop_type}' on {date}")
            return []
        summary = json.loads(blob.download_as_text())
        return list(summary.keys())

    def load(self, property_types: list[str], table_name: str) -> None:
        '''Upserts last_seen for the latest stage-1 run's listing IDs across all property types.'''
        self.set_bucket()
        if self.bigquery_client is None:
            self.set_bigquery_client()

        # A listing_id can show up under more than one property type (e.g. cross-listed
        # ads), so dedupe by id before the MERGE — it requires at most one source row
        # per target row.
        seen: dict[str, str] = {}
        for prop_type in property_types:
            date = self._latest_date(prop_type)
            if date is None:
                logger.warning(f"No scrape dates found for '{prop_type}', skipping")
                continue
            listing_ids = self._read_listing_ids(prop_type, date)
            for lid in listing_ids:
                seen[lid] = max(date, seen[lid]) if lid in seen else date
            logger.info(f"'{prop_type}': {len(listing_ids)} listings present as of {date}")

        if not seen:
            logger.warning("No listings found across any property type; skipping presence update.")
            return

        rows = [{"listing_id": lid, "last_seen": date} for lid, date in seen.items()]

        staging_table = f"{table_name}_staging"
        load_job = self.bigquery_client.load_table_from_json(
            rows,
            staging_table,
            job_config=bigquery.LoadJobConfig(
                write_disposition="WRITE_TRUNCATE",
                schema=LISTING_PRESENCE_SCHEMA,
            ),
        )
        load_job.result()

        self.bigquery_client.query(f'''
            MERGE `{table_name}` T
            USING `{staging_table}` S
            ON T.listing_id = S.listing_id
            WHEN MATCHED THEN UPDATE SET last_seen = S.last_seen
            WHEN NOT MATCHED THEN INSERT (listing_id, last_seen) VALUES (S.listing_id, S.last_seen)
        ''').result()

        self.bigquery_client.delete_table(staging_table, not_found_ok=True)
        logger.info(f"listing_presence upserted with {len(rows)} listings seen across {len(property_types)} property type(s).")
