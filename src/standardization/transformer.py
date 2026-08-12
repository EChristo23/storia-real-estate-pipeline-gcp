
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery, storage

logger = logging.getLogger(__name__)
PARTITION_SIZE = 500

class Transformer:
    def __init__(self, config, type):
        self.config = config
        self.type = type   
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
        if self.config is None:
            raise ValueError("Configuration is not set.")
        self.bucket = self.storage_client.bucket(self.config['gcs']['raw_bucket'])


    def get_watermark(self, table_name):
        '''Fetches the watermark date for self.type from the watermark table. Returns None if no row exists.'''
        if self.bigquery_client is None:
            self.set_bigquery_client()
        query = f'''
            SELECT last_scrape_date
            FROM `{table_name}`
            WHERE property_type = '{self.type}'
            LIMIT 1'''
        query_job = self.bigquery_client.query(query)
        result = query_job.result()
        try:
            row = next(iter(result))
            return row['last_scrape_date']
        except StopIteration:
            return None


    def get_blobs(self, max_date = '2026-01-01', prefix = "detail/"):
        '''Reads a from the raw bucket and returns a list of blob names that have a date greater than the specified max_date.'''
        if self.bucket is None:
            raise ValueError("Bucket is not set. Please call set_bucket() before calling get_blobs().")
        bucket = self.bucket
        blobs = bucket.list_blobs(prefix=f"{self.type}/{prefix}")
        blobs_selection = []
        for blob in blobs:
            data = blob.name.split("/")
            if data[-2] > max_date:
                blobs_selection.append(blob.name)
        return blobs_selection
    
    def read_blob(self, blob_name: str) -> dict:
        '''Reads the content of a blob from the raw bucket.'''
        if self.bucket is None:
            raise ValueError("Bucket is not set. Please call set_bucket() before calling read_blob().")
        blob = self.bucket.blob(blob_name)
        content = blob.download_as_text(encoding='utf-8')
        content = json.loads(content) # return as a dictionary
        return content
    
    def transform_blob(self, blob_name: str, blob: dict) -> tuple[dict, dict]:
        '''Transforms a detail blob into (listing_row, contact_row) matching the standardized schema.'''
        unified_ad = blob['pageProps']['unifiedAd']
        ad = blob['pageProps']['ad']
        attrs = ad.get('attributes') or {}

        # --- pipeline metadata ---
        listing = {}
        listing['id'] = str(unified_ad['id'])
        listing['property_type'] = self.type
        listing['scrape_date'] = blob_name.split("/")[-2]

        # --- identifiers ---
        listing['url'] = ad.get('url')
        listing['external_id'] = (unified_ad.get('source') or {}).get('externalId')
        listing['source_id'] = (unified_ad.get('source') or {}).get('id')
        listing['source_type'] = (unified_ad.get('source') or {}).get('sourceType')
        listing['source_type_name'] = (unified_ad.get('source') or {}).get('__typename')

        # --- advertiser ---
        listing['advertiser_type'] = ad.get('advertiserType')
        listing['advert_type'] = ad.get('advertType')

        # --- content ---
        listing['title'] = ad.get('title')
        listing['description'] = ad.get('description')

        # --- price (unifiedAd.price.salePrice) ---
        sale_price = (unified_ad.get('price') or {}).get('salePrice') or {}
        listing['price'] = sale_price.get('value')
        listing['currency'] = sale_price.get('currency')
        listing['is_negotiable'] = (unified_ad.get('price') or {}).get('isNegotiable')

        # --- area ---
        listing['area'] = attrs.get('m')
        listing['terrain_area'] = attrs.get('terrain_area')

        # --- building ---
        listing['build_year'] = attrs.get('build_year')
        listing['building_type'] = attrs.get('building_type')
        listing['building_material'] = attrs.get('building_material')
        listing['building_ownership'] = attrs.get('building_ownership')
        listing['construction_status'] = attrs.get('construction_status')
        listing['market'] = attrs.get('market')
        listing['roofing'] = attrs.get('roofing')
        listing['garret_type'] = attrs.get('garret_type')
        listing['is_bungalow'] = attrs.get('is_bungalow')

        # --- floor ---
        listing['floor_no'] = attrs.get('floor_no')
        listing['building_floors_num'] = attrs.get('building_floors_num')
        listing['floors_num'] = attrs.get('floors_num')

        # --- rooms / condition ---
        listing['rooms_num'] = attrs.get('rooms_num')
        listing['windows_type'] = attrs.get('windows_type')
        listing['free_from'] = attrs.get('free_from')

        # --- heating ---
        listing['heating'] = attrs.get('heating')
        listing['heating_types'] = attrs.get('heating_types') or []

        # --- array attributes ---
        listing['access_types'] = attrs.get('access_types') or []
        listing['equipment_types'] = attrs.get('equipment_types') or []
        listing['extras_types'] = attrs.get('extras_types') or []
        listing['fence_types'] = attrs.get('fence_types') or []
        listing['garage_types'] = attrs.get('garage_types') or []
        listing['media_types'] = attrs.get('media_types') or []
        listing['security_types'] = attrs.get('security_types') or []

        # --- location ---
        location = ad.get('location') or {}
        coords = location.get('coordinates') or {}
        listing['latitude'] = coords.get('latitude')
        listing['longitude'] = coords.get('longitude')
        street = (location.get('address') or {}).get('street') or {}
        listing['street_name'] = street.get('name') if isinstance(street, dict) else None
        geo_locs = (location.get('reverseGeocoding') or {}).get('locations') or []
        listing['county'] = next((l['name'] for l in geo_locs if l.get('locationLevel') == 'county'), None)
        listing['city'] = next((l['name'] for l in geo_locs if l.get('locationLevel') in ('county_capital', 'city')), None)
        listing['commune'] = next((l['name'] for l in geo_locs if l.get('locationLevel') in ('commune', 'village')), None)

        # --- owner ---
        owner = ad.get('owner') or {}
        listing['owner_id'] = str(owner['id']) if owner.get('id') is not None else None
        listing['owner_type'] = owner.get('type')
        listing['owner_name'] = owner.get('name')

        # --- dates ---
        listing['created_at'] = ad.get('createdAt')
        listing['updated_at'] = ad.get('modifiedAt')
        listing['pushed_up_at'] = ad.get('pushedUpAt')

        # --- media ---
        listing['images'] = [img['large'] for img in (ad.get('images') or []) if img.get('large')]

        # --- contact ---
        contact_details = ad.get('contactDetails') or {}
        contact = {
            'listing_id': listing['id'],
            'scrape_date': listing['scrape_date'],
            'name': contact_details.get('name'),
            'contact_type': contact_details.get('type'),
            'phones': contact_details.get('phones') or [],
        }

        return listing, contact


    def write_rows(self, table_name: str, rows: list[dict], partition_size: int = 500) -> None:
        '''Writes a list of rows to the specified BigQuery table.'''
        if self.bigquery_client is None:
            self.set_bigquery_client()
        table = self.bigquery_client.get_table(table_name)
        for i in range(0, len(rows), partition_size):
            partition = rows[i:i + partition_size]            
            errors = self.bigquery_client.insert_rows_json(table, partition)
            if errors:
                raise RuntimeError(f"Row write failed: {errors}")
            

    def write_watermark(self, table_name: str, scrape_date: str) -> None:
        '''Upserts the watermark row for self.type. Deletes any existing row first, then inserts.'''
        if self.bigquery_client is None:
            self.set_bigquery_client()
        self.bigquery_client.query(
            f"DELETE FROM `{table_name}` WHERE property_type = '{self.type}'"
        ).result()
        errors = self.bigquery_client.insert_rows_json(
            self.bigquery_client.get_table(table_name),
            [{'property_type': self.type, 'last_scrape_date': scrape_date}],
        )
        if errors:
            raise RuntimeError(f"Watermark write failed: {errors}")

    def transform(self):
        # Set up clients and bucket
        self.set_storage_client()
        self.set_bigquery_client()
        self.set_bucket()

        # Tables
        bq = self.config['bigquery']
        watermark_table = f"{bq['project']}.{bq['dataset']}.{bq['watermark_table']}"
        listings_table  = f"{bq['project']}.{bq['dataset']}.{bq['listings_table']}"
        contacts_table  = f"{bq['project']}.{bq['dataset']}.{bq['contacts_table']}"

        #  Get the watermark date for this property type
        watermark_date = self.get_watermark(table_name=watermark_table)
        if watermark_date is None:
            logger.info(f"No watermark found for property type '{self.type}'. Processing all blobs.")
            watermark_date = '2026-01-01'  # Default to a very old date if no watermark exists

        # Get the list of blobs to process
        blobs_list = self.get_blobs(max_date=watermark_date, prefix="detail/")
        listings_list = []
        contacts_list = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(self.read_blob, name): name for name in blobs_list}
            for future in as_completed(futures):
                blob_name = futures[future]
                try:
                    blob_content = future.result()
                    listing_row, contact_row = self.transform_blob(blob_name, blob_content)
                    listings_list.append(listing_row)
                    contacts_list.append(contact_row)
                except (json.JSONDecodeError, KeyError, GoogleAPIError) as e:
                    # TODO: analyze blob structure at fetch time in the detail scraper
                    # and route unrecognized/malformed blobs to a dead-letter GCS prefix
                    # (e.g. casa/detail/unprocessable/) instead of silently skipping here
                    logger.warning("Skipping blob %s: %s", blob_name, e)
        
        # Write the transformed rows to BigQuery
        if listings_list:
            self.write_rows(table_name=listings_table, rows=listings_list, partition_size=PARTITION_SIZE)
        if contacts_list:
            self.write_rows(table_name=contacts_table, rows=contacts_list, partition_size=PARTITION_SIZE)

        # Update the watermark with the latest scrape date
        if blobs_list:
            latest_scrape_date = max(blob_name.split("/")[-2] for blob_name in blobs_list)
            self.write_watermark(table_name=watermark_table, scrape_date=latest_scrape_date)
            logger.info(f"Transformation complete for property type '{self.type}'. Processed {len(listings_list)} listings and {len(contacts_list)} contacts. Updated watermark to {latest_scrape_date}.")
        else:
            logger.info(f"No new blobs found for '{self.type}'.")

    