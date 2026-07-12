#%%
import asyncio
import json
import logging
import random
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from google.cloud import storage

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

_MAX_RETRIES = 3
_BACKOFF_BASE = 5  # seconds
_CONCURRENCY = 5


class Scrapper:
    def __init__(self, type="casa", n_pages=None):
        self.type = type
        self.build_id = None
        self.n_pages = n_pages
        self.semaphore = asyncio.Semaphore(_CONCURRENCY)

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
        }

    def setup(self) -> None:
        '''Set up the scraper by fetching the build ID and page count.'''
        try:
            with httpx.Client(http2=True) as client:
                response = client.get(
                    f"https://www.storia.ro/ro/rezultate/vanzare/{self.type}/toata-romania?crawl=true&limit=72&view=map",
                    headers=self._headers(),
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                next_data_script = soup.find("script", id="__NEXT_DATA__")
                if next_data_script:
                    full_data = json.loads(next_data_script.string)
                    self.build_id = full_data.get("buildId")
                    try:
                        listing_data = full_data["props"]["pageProps"]["tracking"]["listing"]
                        page_count = listing_data.get("page_count", 1)
                        self.n_pages = min(self.n_pages, page_count) if self.n_pages is not None else page_count
                    except KeyError as e:
                        logger.warning(f"Structure change: could not find key {e}")
        except Exception as e:
            logger.critical(f"Setup failed: {e}")

    def _write_page(self, bucket: storage.Bucket, page: int, data: dict) -> None:
        '''Write the scraped data for a page to Google Cloud Storage.'''
        date_str = datetime.now().strftime("%Y-%m-%d")
        blob_name = f"{self.type}/{date_str}/{date_str}_{page}.json"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type="application/json")
        logger.info(f"[page {page}] Written to gs://{bucket.name}/{blob_name}")

    async def _fetch_page(self, client: httpx.AsyncClient, bucket: storage.Bucket, page: int) -> dict | None:
        '''Fetch a single page of listings asynchronously and write it to GCS with retries and exponential backoff.'''
        url = (
            f"https://www.storia.ro/_next/data/{self.build_id}/ro/rezultate/vanzare/"
            f"{self.type}/toata-romania.json?crawl=true&limit=72"
            f"&searchingCriteria=vanzare&searchingCriteria={self.type}"
            f"&searchingCriteria=toata-romania&page={page}"
        )
        async with self.semaphore:
            await asyncio.sleep(random.uniform(1.5, 4.0))
            for attempt in range(_MAX_RETRIES):
                try:
                    response = await client.get(url, headers=self._headers())
                    if response.status_code in (429, 403, 500, 503):
                        wait = _BACKOFF_BASE * (2 ** attempt)
                        logger.warning(f"[page {page}] HTTP {response.status_code} — backing off {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    self._write_page(bucket, page, data)
                    return data
                except httpx.RequestError as e:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"[page {page}] Request error: {e} — retrying in {wait}s")
                    await asyncio.sleep(wait)
            logger.error(f"[page {page}] Failed after {_MAX_RETRIES} attempts")
            return None

    def _write_manifest(self, bucket: storage.Bucket, fetched: list[int], failed: list[int], listings_count: int) -> None:
        '''Write a manifest file summarizing the scraping results to GCS.'''
        date_str = datetime.now().strftime("%Y-%m-%d")
        blob_name = f"{self.type}/{date_str}/manifest.json"
        manifest = {
            "date": date_str,
            "type": self.type,
            "total_pages": self.n_pages,
            "fetched": fetched,
            "failed": failed,
            "listings_count": listings_count,
        }
        bucket.blob(blob_name).upload_from_string(
            json.dumps(manifest, ensure_ascii=False), content_type="application/json"
        )
        if failed:
            logger.warning(f"Manifest written — {len(fetched)}/{self.n_pages} pages OK, failed: {failed}")
        else:
            logger.info(f"Manifest written — {len(fetched)}/{self.n_pages} pages OK, {listings_count} listings")

    def _write_listing_summary(self, bucket: storage.Bucket, results: list[dict | None]) -> None:
        summary: dict[str, str | None] = {}
        for r in results:
            if r is None:
                continue
            for item in r.get("pageProps", {}).get("data", {}).get("searchAds", {}).get("items", []):
                lid = str(item["id"])
                if lid not in summary:
                    summary[lid] = item.get("pushedUpAt")
        date_str = datetime.now().strftime("%Y-%m-%d")
        blob_name = f"{self.type}/{date_str}/listing_summary.json"
        bucket.blob(blob_name).upload_from_string(
            json.dumps(summary, ensure_ascii=False), content_type="application/json"
        )
        logger.info(f"Listing summary written — {len(summary)} unique listings for {date_str}")

    async def scrape(self, bucket_name: str) -> list[dict]:
        gcs_client = storage.Client()
        bucket = gcs_client.bucket(bucket_name)
        pages = list(range(1, self.n_pages + 1))
        async with httpx.AsyncClient(http2=True) as client:
            tasks = [self._fetch_page(client, bucket, page) for page in pages]
            results = await asyncio.gather(*tasks)
        fetched = [page for page, r in zip(pages, results) if r is not None]
        failed  = [page for page, r in zip(pages, results) if r is None]
        listings_count = sum(
            len(r.get("pageProps", {}).get("data", {}).get("searchAds", {}).get("items", []))
            for r in results if r is not None
        )
        self._write_manifest(bucket, fetched, failed, listings_count)
        self._write_listing_summary(bucket, results)
        return [r for r in results if r is not None]

    async def get_coordinate_map(self) -> dict:
        # TODO: endpoint requires a JSON-RPC POST payload — plain GET returns an error.
        # Inspect network traffic to find the correct request body before implementing.
        raise NotImplementedError("get_coordinate_map: correct JSON-RPC payload not yet determined")


_DETAIL_CONCURRENCY = 5


class DetailScraper:
    def __init__(self, type: str = "casa", date: str | None = None):
        self.type = type
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self.build_id = None
        self.semaphore = asyncio.Semaphore(_DETAIL_CONCURRENCY)
        self._bucket_name: str | None = None
        self._gcs_client: storage.Client | None = None

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
        }

    def setup(self) -> None:
        try:
            with httpx.Client(http2=True) as client:
                response = client.get(
                    f"https://www.storia.ro/ro/rezultate/vanzare/{self.type}/toata-romania?crawl=true&limit=72&view=map",
                    headers=self._headers(),
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                script = soup.find("script", id="__NEXT_DATA__")
                if script:
                    self.build_id = json.loads(script.string).get("buildId")
        except Exception as e:
            logger.critical(f"DetailScraper setup failed: {e}")

    def _read_slugs(self, bucket: storage.Bucket) -> list[dict]:
        prefix = f"{self.type}/{self.date}/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        if not blobs:
            logger.warning(f"No Bronze list blobs found at gs://{bucket.name}/{prefix}")
            return []

        seen: dict[int, dict] = {}
        skip = ("manifest.json", "listing_summary.json")
        for blob in [b for b in blobs if not b.name.endswith(skip)]:
            try:
                data = json.loads(blob.download_as_text())
                items = data["pageProps"]["data"]["searchAds"]["items"]
                for item in items:
                    lid = item["id"]
                    if lid not in seen:
                        seen[lid] = {"slug": item["slug"], "pushed_up_at": item.get("pushedUpAt")}
            except Exception as e:
                logger.warning(f"Could not parse {blob.name}: {e}")

        logger.info(f"Found {len(seen)} unique slugs from {len(blobs)} list blobs")
        return [{"id": lid, **v} for lid, v in seen.items()]

    def _detail_blob_name(self, listing_id: int) -> str:
        return f"{self.type}/detail/{self.date}/{listing_id}.json"

    def _gcs_bucket(self) -> storage.Bucket:
        if self._gcs_client is None:
            self._gcs_client = storage.Client()
        return self._gcs_client.bucket(self._bucket_name)

    def _write_detail(self, listing_id: int, data: dict, pushed_up_at: str | None = None) -> None:
        blob_name = self._detail_blob_name(listing_id)
        for attempt in range(2):
            try:
                blob = self._gcs_bucket().blob(blob_name)
                blob.metadata = {"pushed_up_at": pushed_up_at or ""}
                blob.upload_from_string(
                    json.dumps(data, ensure_ascii=False), content_type="application/json"
                )
                logger.info(f"[{listing_id}] Written to gs://{self._bucket_name}/{blob_name}")
                return
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[{listing_id}] GCS write failed ({e}), reconnecting")
                    self._gcs_client = None
                else:
                    raise

    def _load_existing_pushed_up_at(self, bucket: storage.Bucket) -> dict[int, str]:
        prefix = f"{self.type}/detail/"
        known: dict[int, str] = {}
        for blob in bucket.list_blobs(prefix=prefix):
            filename = blob.name.rsplit("/", 1)[-1]
            if not filename.endswith(".json"):
                continue
            try:
                lid = int(filename[:-5])
            except ValueError:
                continue
            pua = (blob.metadata or {}).get("pushed_up_at")
            if pua is not None:
                known[lid] = pua
        logger.info(f"Loaded {len(known)} existing detail records for incremental check")
        return known

    def _load_previous_listing_summary(self, bucket: storage.Bucket) -> dict[int, str | None] | None:
        iterator = bucket.list_blobs(prefix=f"{self.type}/", delimiter="/")
        dates = []
        for page in iterator.pages:
            for prefix in page.prefixes:
                date = prefix.rstrip("/").split("/")[-1]
                if date not in (self.date, "detail"):
                    dates.append(date)
        if not dates:
            return None
        prev_date = sorted(dates)[-1]
        try:
            data = json.loads(bucket.blob(f"{self.type}/{prev_date}/listing_summary.json").download_as_text())
            result = {int(k): v for k, v in data.items()}
            logger.info(f"Loaded previous Stage 1 summary from {prev_date} ({len(result)} listings)")
            return result
        except Exception as e:
            logger.warning(f"Could not load listing summary for {prev_date}: {e}")
            return None

    def _log_diff(self, slugs: list[dict], prev_stage1: dict[int, str | None] | None) -> None:
        if prev_stage1 is None:
            logger.info("Pre-fetch diff — no previous Stage 1 summary found, treating all listings as new")
            return
        today_ids = {item["id"] for item in slugs}
        new, updated, unchanged = 0, 0, 0
        for item in slugs:
            lid = item["id"]
            pua = item.get("pushed_up_at")
            if lid not in prev_stage1:
                new += 1
            elif prev_stage1[lid] != pua:
                updated += 1
            else:
                unchanged += 1
        delisted = sum(1 for lid in prev_stage1 if lid not in today_ids)
        logger.info(
            f"Pre-fetch diff — {new} new, {updated} updated, {unchanged} unchanged, "
            f"{delisted} absent from today's Stage 1 (possibly delisted)"
        )

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        listing_id: int,
        slug: str,
        pushed_up_at: str | None = None,
        existing: dict[int, str] | None = None,
    ) -> dict | None:
        if existing is not None and listing_id in existing and existing[listing_id] == (pushed_up_at or ""):
            logger.debug(f"[{listing_id}] Unchanged since last run, skipping")
            return None

        async with self.semaphore:
            await asyncio.sleep(random.uniform(2.0, 5.0))
            build_id_refreshed = False
            for attempt in range(_MAX_RETRIES):
                try:
                    url = f"https://www.storia.ro/_next/data/{self.build_id}/ro/oferta/{slug}.json"
                    response = await client.get(url, headers=self._headers())
                    if response.status_code in (404, 410, 500):
                        if not build_id_refreshed:
                            logger.warning(f"[{listing_id}] HTTP {response.status_code} — refreshing build_id")
                            await asyncio.get_event_loop().run_in_executor(None, self.setup)
                            build_id_refreshed = True
                            continue
                        logger.warning(f"[{listing_id}] HTTP {response.status_code} after refresh — listing gone, skipping")
                        return None
                    if response.status_code in (429, 403, 503):
                        wait = _BACKOFF_BASE * (2 ** attempt)
                        logger.warning(f"[{listing_id}] HTTP {response.status_code} — backing off {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    self._write_detail(listing_id, data, pushed_up_at)
                    return data
                except httpx.RequestError as e:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"[{listing_id}] Request error: {e} — retrying in {wait}s")
                    await asyncio.sleep(wait)
            logger.error(f"[{listing_id}] Failed after {_MAX_RETRIES} attempts")
            return None

    async def enrich(self, bucket_name: str) -> list[dict]:
        self._bucket_name = bucket_name
        gcs_client = storage.Client()
        bucket = gcs_client.bucket(bucket_name)
        slugs = self._read_slugs(bucket)
        if not slugs:
            return []

        existing = self._load_existing_pushed_up_at(bucket)
        prev_stage1 = self._load_previous_listing_summary(bucket)
        self._log_diff(slugs, prev_stage1)
        async with httpx.AsyncClient(http2=True) as client:
            tasks = [
                self._fetch_detail(client, item["id"], item["slug"], item.get("pushed_up_at"), existing)
                for item in slugs
            ]
            results = await asyncio.gather(*tasks)

        fetched = [r for r in results if r is not None]
        logger.info(f"Enrichment complete — {len(fetched)}/{len(slugs)} listings fetched")
        return fetched
