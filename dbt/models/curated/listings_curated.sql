-- One row per listing_id: the most recent scrape_date snapshot only.
-- standardized.listings intentionally keeps one row per (id, scrape_date);
-- this resolves those duplicates down to the current state of each listing.
--
-- is_active reflects presence in the latest stage-1 (list-page) run rather
-- than scrape_date, since scrape_date only advances when a listing's content
-- actually changes — an unchanged-but-still-live listing would otherwise look
-- identical to a delisted one.
--
-- listing_presence holds one row per listing ever seen (last_seen advances
-- while a listing keeps appearing, stays put once it stops) — so a listing is
-- only active if its last_seen matches the most recent run, not merely if a
-- row exists at all.

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
),

most_recent_run as (
    select max(last_seen) as last_seen
    from {{ source('standardized', 'listing_presence') }}
)

select
    latest.*,
    presence.last_seen,
    coalesce(presence.last_seen = most_recent_run.last_seen, false) as is_active
from latest
left join {{ source('standardized', 'listing_presence') }} as presence
    on latest.id = presence.listing_id
cross join most_recent_run
