import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from src import config
from src.ingestion.scraper import DetailScraper, Scrapper
from src.standardization.loader import PresenceLoader
from src.standardization.transformer import Transformer

load_dotenv()

DBT_PROJECT_DIR = Path(__file__).parent / "dbt"


def _setup_logging():
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            return json.dumps({
                "severity": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            })

    handlers = []

    # stdout — JSON for Cloud Run / Cloud Logging
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JsonFormatter())
    handlers.append(stdout_handler)

    # file — plain text, only when LOG_DIR is set (local dev)
    log_dir = os.getenv("LOG_DIR")
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=Path(log_dir) / "scraper.log",
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handlers.append(file_handler)

    logging.basicConfig(level=logging.INFO, handlers=handlers)


async def run_scraper(prop_type: str, n_pages: int, bucket_name: str, base_url: str):
    logger = logging.getLogger(__name__)
    scraper = Scrapper(type=prop_type, n_pages=n_pages, base_url=base_url)
    logger.info(f"Starting scraper for '{prop_type}'")
    scraper.setup()
    if not scraper.build_id:
        logger.critical(f"Setup failed for '{prop_type}' — no build_id, aborting")
        return
    logger.info(f"Setup complete — build_id={scraper.build_id}, pages={scraper.n_pages}")
    results = await scraper.scrape(bucket_name=bucket_name)
    logger.info(f"Scrape complete — {len(results)}/{scraper.n_pages} pages fetched")



async def run_detail_scraper(prop_type: str, bucket_name: str, base_url: str):
    logger = logging.getLogger(__name__)
    scraper = DetailScraper(type=prop_type, base_url=base_url)
    logger.info(f"Starting detail scraper for '{prop_type}'")
    scraper.setup()
    if not scraper.build_id:
        logger.critical(f"Detail scraper setup failed for '{prop_type}' — no build_id, aborting")
        return
    logger.info(f"Detail scraper setup complete — build_id={scraper.build_id}, date={scraper.date}")
    results = await scraper.enrich(bucket_name=bucket_name)
    logger.info(f"Enrichment complete — {len(results)} listings fetched for '{prop_type}'")


def run_transformer(prop_type: str, cfg: dict):
    logger = logging.getLogger(__name__)
    transformer = Transformer(config=cfg, type=prop_type)
    logger.info(f"Starting transformer for '{prop_type}'")
    transformer.transform()
    logger.info(f"Transformation complete for '{prop_type}'")


def run_presence_loader(cfg: dict):
    logger = logging.getLogger(__name__)
    bq = cfg["bigquery"]
    table_name = f"{bq['project']}.{bq['dataset']}.{bq['listing_presence_table']}"
    logger.info("Rebuilding listing_presence from the latest stage-1 run")
    loader = PresenceLoader(config=cfg)
    loader.load(property_types=cfg["scraping"]["property_types"], table_name=table_name)
    logger.info("listing_presence rebuild complete")


def run_curation():
    logger = logging.getLogger(__name__)
    logger.info("Starting dbt curation run")
    try:
        subprocess.run(
            ["dbt", "run", "--project-dir", str(DBT_PROJECT_DIR), "--profiles-dir", str(DBT_PROJECT_DIR)],
            check=True,
        )
        logger.info("Curation complete")
    except subprocess.CalledProcessError as e:
        logger.critical(f"dbt run failed with exit code {e.returncode}")
        raise RuntimeError(f"dbt run failed with exit code {e.returncode}") from e


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, choices=[1, 2, 3, 4], nargs="+", help="Stages to run (e.g. --stage 1 2). Default: all.")
    args = parser.parse_args()

    _setup_logging()
    cfg = config.load()
    n_pages = cfg["scraping"].get("n_pages")
    bucket_name = cfg["gcs"]["raw_bucket"]

    # Ingestion stages:
    if not args.stage or 1 in args.stage:
        for prop_type in cfg["scraping"]["property_types"]:
            await run_scraper(prop_type, n_pages=n_pages, bucket_name=bucket_name, base_url=cfg["scraping"]["base_url"])
        run_presence_loader(cfg)

    if not args.stage or 2 in args.stage:
        for prop_type in cfg["scraping"]["property_types"]:
            await run_detail_scraper(prop_type, bucket_name=bucket_name, base_url=cfg["scraping"]["base_url"])

    if not args.stage or 3 in args.stage:
        for prop_type in cfg["scraping"]["property_types"]:
            run_transformer(prop_type, cfg=cfg)

    if not args.stage or 4 in args.stage:
        run_curation()


if __name__ == "__main__":
    asyncio.run(main())
