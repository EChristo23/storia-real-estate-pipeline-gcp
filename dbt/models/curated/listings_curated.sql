-- One row per listing_id: the most recent scrape_date snapshot only.
-- standardized.listings intentionally keeps one row per (id, scrape_date);
-- this resolves those duplicates down to the current state of each listing.
--
-- is_active reflects presence in the latest stage-1 (list-page) run rather
-- than scrape_date, since scrape_date only advances when a listing's content
-- actually changes — an unchanged-but-still-live listing would otherwise look
-- identical to a delisted one.

with ranked as (
    select
        *,
        row_number() over (partition by id order by scrape_date desc) as rn
    from {{ source('standardized', 'listings') }}
),

latest as (
    select * except (rn)
    from ranked
    where rn = 1
)

select
    latest.*,
    presence.listing_id is not null as is_active
from latest
left join {{ source('standardized', 'listing_presence') }} as presence
    on latest.id = presence.listing_id
