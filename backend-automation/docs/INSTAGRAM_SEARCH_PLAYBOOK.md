# Instagram Search Playbook (Eshway Leadway)

Practical operator guidance for discovering (1) website-development **clients** and (2) **agency collaboration** partners on Instagram (2024–2026).

## How Instagram search ranks (what matters)

Instagram search behaves like a text search engine over accounts + content:

1. **Text match** — query vs username, **display name** (highest leverage), bio, captions, alt text, on-screen/spoken Reel text, hashtags, places.
2. **Searcher context** — accounts you’ve interacted with rank higher for you.
3. **Popularity / engagement** — clicks, follows, saves, shares push candidates up once they match.

Hashtags are now **category labels**, not a discovery engine. Instagram removed hashtag following and the “Recent” tab; broad tags are spam-heavy. For lead harvesting, **Accounts / People results beat hashtag post grids**.

Leadway therefore prefers:

1. Authenticated **topsearch / users-search** APIs (Accounts)
2. Search **typeahead Accounts** UI
3. Hashtag/keyword **post-grid author harvest** only as fallback

## Prefer: Accounts tab / People search

| Surface | Use for Leadway? | Why |
|--------|------------------|-----|
| Accounts / People | **Primary** | Returns real business handles matching name/bio keywords |
| Typeahead (Search box) | **Primary fallback** | Same ranking as Accounts; easy to scrape rows |
| Keyword `/explore/search/keyword/` | Weak | Often a Reels/post grid; authors hard/unreliable |
| Hashtag tag pages | Weak / last resort | Mix of creators + spam; Recent tab gone |
| Location pages | Optional later | Good for local businesses once geo is defined |
| Related accounts | Optional later | High precision after one good seed profile |

## Query patterns that work

### A) Website-development clients (identity phrases)

Businesses put **role + niche** in the name field (`Priya | Fitness Coach`), not “need a website”.

High-signal examples:

- `fitness coach`, `business coach`, `life coach`, `online coach`
- `ecommerce brand`, `online boutique`, `shopify brand`
- `restaurant owner`, `salon owner`, `clinic owner`, `dentist clinic`
- `real estate agent`, `interior designer`, `wedding photographer`
- `startup founder`, `small business owner`, `course creator`

Geo hybrids (when targeting a city): `mumbai fitness coach`, `dubai salon`, `bangalore cafe`.

### B) Agency collaboration partners

- `branding agency`, `brand design studio`, `creative agency`
- `social media agency`, `digital marketing agency`, `performance marketing`
- `seo agency`, `content agency`
- `ui ux designer`, `ui ux studio`, `product design studio`
- `graphic design studio`, `brand designer`

These phrases commonly appear in agency display names and bios, so Accounts search surfaces usable handles.

## Anti-patterns (junk / zero harvest)

Avoid:

- **Single generic tokens**: `agency`, `web`, `design`, `marketing`, `blog`, `popular`
- **Ultra-broad hashtags**: `#agency`, `#marketing`, `#webdesign`, `#entrepreneur`
- **Intent SEO phrases**: `coach website`, `small business website`, `need website` — rarely match account names → **0 Accounts hits**
- **Harvesting footer/chrome paths** as usernames (`about-us`, `blog`, `web`, `popular`, `directory`)
- **Relying only on keyword post grids** — grids can be empty or yield unreplicable authors

## Keyword strategy for the Eshway campaign

Mix ~50% CLIENT identity phrases + ~50% COLLABORATION agency phrases.

Prefer **2–4 word** plain queries (no `#`) for Accounts APIs. Keep niche hashtags ≤20% of the queue.

Replace weak unused seeds that look like Google SEO (`* website`) with identity labels the Accounts index actually matches.

## Operational checklist

1. Search Accounts-first for the next unused keyword.
2. Filter junk handles before enrich/qualify.
3. Qualify CLIENT vs COLLABORATION from bio + website signals (messaging skill).
4. If a query returns 0 Accounts, mark it weak and prefer identity synonyms — don’t burn budget opening empty post grids.
