from dotenv import load_dotenv

load_dotenv()

from google.cloud import bigquery

from src import config
from src.standardization.schema import (
    LISTING_CONTACTS_SCHEMA,
    LISTING_PRESENCE_SCHEMA,
    LISTING_SCHEMA,
    WATERMARK_SCHEMA,
)


def main():

    cfg = config.load()
    client = bigquery.Client()
    listings_table = bigquery.Table(
        f"{cfg['bigquery']['project']}.{cfg['bigquery']['dataset']}.{cfg['bigquery']['listings_table']}",
        schema=LISTING_SCHEMA
    )
    contacts_table = bigquery.Table(
        f"{cfg['bigquery']['project']}.{cfg['bigquery']['dataset']}.{cfg['bigquery']['contacts_table']}",
        schema=LISTING_CONTACTS_SCHEMA
    )
    watermark_table = bigquery.Table(
        f"{cfg['bigquery']['project']}.{cfg['bigquery']['dataset']}.{cfg['bigquery']['watermark_table']}",
        schema=WATERMARK_SCHEMA
    )
    listing_presence_table = bigquery.Table(
        f"{cfg['bigquery']['project']}.{cfg['bigquery']['dataset']}.{cfg['bigquery']['listing_presence_table']}",
        schema=LISTING_PRESENCE_SCHEMA
    )
    for t in [listings_table, contacts_table, watermark_table, listing_presence_table]:
        client.create_table(
            table=t,
            exists_ok=True
        )
        print(f"Table {t.table_id} created successfully or it already exists.")

if __name__ == "__main__":
    main()