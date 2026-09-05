import json
import logging

from google.cloud import bigquery, storage

from src.standardization.schema import LISTING_PRESENCE_SCHEMA

logger = logging.getLogger(__name__)


class PresenceLoader:
    '''Rebuilds the listing_presence table from each property type's most recent
    stage-1 (list-page) scrape. The table is fully replaced on every run — it
    reflects only the latest run, not a history of past runs.'''

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
        '''Replaces the presence table with the latest stage-1 run's listing IDs for each property type.'''
        self.set_bucket()
        if self.bigquery_client is None:
            self.set_bigquery_client()

        rows = []
        for prop_type in property_types:
            date = self._latest_date(prop_type)
            if date is None:
                logger.warning(f"No scrape dates found for '{prop_type}', skipping")
                continue
            listing_ids = self._read_listing_ids(prop_type, date)
            rows.extend({"listing_id": lid, "date": date} for lid in listing_ids)
            logger.info(f"'{prop_type}': {len(listing_ids)} listings present as of {date}")

        job = self.bigquery_client.load_table_from_json(
            rows,
            table_name,
            job_config=bigquery.LoadJobConfig(
                write_disposition="WRITE_TRUNCATE",
                schema=LISTING_PRESENCE_SCHEMA,
            ),
        )
        job.result()
        logger.info(f"listing_presence replaced with {len(rows)} rows across {len(property_types)} property type(s).")
