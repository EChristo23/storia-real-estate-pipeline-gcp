-- One row per listing_id: the contact info from the most recent scrape_date only.
-- Mirrors listings_curated.sql's dedup — standardized.contacts keeps one row
-- per (listing_id, scrape_date).

with ranked as (
    select
        *,
        row_number() over (partition by listing_id order by scrape_date desc) as rn
    from {{ source('standardized', 'contacts') }}
)

select * except (rn)
from ranked
where rn = 1
