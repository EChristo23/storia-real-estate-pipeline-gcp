'''BigQuery schemas for the standardized layer.'''

from google.cloud import bigquery

# One row per listing per scrape_date.
# (id, scrape_date) is the composite key — duplicates across dates are intentional
# and resolved in the curated layer.
# All source string attributes are kept as STRING; numeric/temporal types are
# only used where the source JSON already produces that native type.

LISTING_SCHEMA = [
    # --- pipeline metadata ---
    bigquery.SchemaField("id",            "STRING", mode="REQUIRED"),
    bigquery.SchemaField("property_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("scrape_date",   "DATE",   mode="REQUIRED"),

    # --- identifiers / slugs ---
    bigquery.SchemaField("slug",        "STRING", mode="NULLABLE"),
    bigquery.SchemaField("external_id", "STRING", mode="NULLABLE"),  # unifiedAd.source.externalId
    bigquery.SchemaField("source_id",   "STRING", mode="NULLABLE"),  # unifiedAd.source.id
    bigquery.SchemaField("source_type", "STRING", mode="NULLABLE"),  # unifiedAd.source.sourceType

    # --- content ---
    bigquery.SchemaField("title",       "STRING", mode="NULLABLE"),
    bigquery.SchemaField("description", "STRING", mode="NULLABLE"),

    # --- price (unifiedAd.price.salePrice) ---
    bigquery.SchemaField("price",         "FLOAT",   mode="NULLABLE"),
    bigquery.SchemaField("currency",      "STRING",  mode="NULLABLE"),
    bigquery.SchemaField("is_negotiable", "BOOLEAN", mode="NULLABLE"),
    bigquery.SchemaField("price_per_m",   "STRING",  mode="NULLABLE"),  # unifiedAd.attributes.price_per_m

    # --- area ---
    bigquery.SchemaField("area",          "STRING", mode="NULLABLE"),  # unifiedAd.attributes.m
    bigquery.SchemaField("terrain_area",  "STRING", mode="NULLABLE"),  # casa only

    # --- building ---
    bigquery.SchemaField("build_year",         "STRING", mode="NULLABLE"),
    bigquery.SchemaField("building_type",      "STRING", mode="NULLABLE"),
    bigquery.SchemaField("building_material",  "STRING", mode="NULLABLE"),
    bigquery.SchemaField("building_ownership", "STRING", mode="NULLABLE"),  # apartament
    bigquery.SchemaField("construction_status","STRING", mode="NULLABLE"),
    bigquery.SchemaField("market",             "STRING", mode="NULLABLE"),
    bigquery.SchemaField("roofing",            "STRING", mode="NULLABLE"),  # casa only
    bigquery.SchemaField("garret_type",        "STRING", mode="NULLABLE"),  # casa only
    bigquery.SchemaField("is_bungalow",        "STRING", mode="NULLABLE"),  # casa only

    # --- floor (field names differ by property type) ---
    bigquery.SchemaField("floor_no",           "STRING", mode="NULLABLE"),  # apartament: which floor
    bigquery.SchemaField("building_floors_num","STRING", mode="NULLABLE"),  # apartament: total floors in building
    bigquery.SchemaField("floors_num",         "STRING", mode="NULLABLE"),  # casa: floors in the house

    # --- rooms / condition ---
    bigquery.SchemaField("rooms_num",          "STRING", mode="NULLABLE"),
    bigquery.SchemaField("windows_type",       "STRING", mode="NULLABLE"),
    bigquery.SchemaField("free_from",          "STRING", mode="NULLABLE"),  # apartament only

    # --- heating (field name differs by property type) ---
    bigquery.SchemaField("heating",            "STRING",   mode="NULLABLE"),   # apartament: single value
    bigquery.SchemaField("heating_types",      "STRING",   mode="REPEATED"),   # casa: array

    # --- array attributes (both types) ---
    bigquery.SchemaField("access_types",    "STRING", mode="REPEATED"),  # casa
    bigquery.SchemaField("equipment_types", "STRING", mode="REPEATED"),  # apartament
    bigquery.SchemaField("extras_types",    "STRING", mode="REPEATED"),
    bigquery.SchemaField("garage_types",    "STRING", mode="REPEATED"),
    bigquery.SchemaField("media_types",     "STRING", mode="REPEATED"),
    bigquery.SchemaField("security_types",  "STRING", mode="REPEATED"),  # apartament

    # --- location (unifiedAd.location) ---
    bigquery.SchemaField("street_name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("latitude",    "FLOAT",  mode="NULLABLE"),
    bigquery.SchemaField("longitude",   "FLOAT",  mode="NULLABLE"),
    bigquery.SchemaField("county",      "STRING", mode="NULLABLE"),  # reverseGeocoding: locationLevel=county
    bigquery.SchemaField("city",        "STRING", mode="NULLABLE"),  # reverseGeocoding: locationLevel=city/county_capital
    bigquery.SchemaField("commune",     "STRING", mode="NULLABLE"),  # reverseGeocoding: locationLevel=commune

    # --- owner (unifiedAd.ownerAccount) ---
    bigquery.SchemaField("owner_id",   "STRING", mode="NULLABLE"),
    bigquery.SchemaField("owner_type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("owner_name", "STRING", mode="NULLABLE"),

    # --- dates ---
    bigquery.SchemaField("created_at",   "TIMESTAMP", mode="NULLABLE"),  # unifiedAd.lifecycle.createdAt
    bigquery.SchemaField("updated_at",   "TIMESTAMP", mode="NULLABLE"),  # unifiedAd.lifecycle.updatedAt
    bigquery.SchemaField("pushed_up_at", "TIMESTAMP", mode="NULLABLE"),  # ad.pushedUpAt

    # --- media ---
    bigquery.SchemaField("images", "STRING", mode="REPEATED"),  # ad.images[].large
]


# One row per listing per scrape_date.
# phones is REPEATED because a contact can have multiple numbers.

LISTING_CONTACTS_SCHEMA = [
    bigquery.SchemaField("listing_id",   "STRING", mode="REQUIRED"),
    bigquery.SchemaField("scrape_date",  "DATE",   mode="REQUIRED"),
    bigquery.SchemaField("name",         "STRING", mode="NULLABLE"),
    bigquery.SchemaField("contact_type", "STRING", mode="NULLABLE"),  # agency / private
    bigquery.SchemaField("phones",       "STRING", mode="REPEATED"),
]

WATERMARK_SCHEMA = [
    bigquery.SchemaField("property_type",    "STRING", mode="REQUIRED"),
    bigquery.SchemaField("last_scrape_date", "DATE",   mode="REQUIRED"),
]