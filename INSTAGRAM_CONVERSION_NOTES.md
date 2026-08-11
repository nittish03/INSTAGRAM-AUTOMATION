# Instagram conversion notes

**Status: READY FOR TESTING after `python manage.py migrate`.**

Hot-path code targets Instagram only (search / qualify / DM). Follow /
check_pending remain as dormant legacy paths; product outreach is DM-first.
Voyager and LinkedIn profile API aliases are removed from the product surface.

## Messaging skill scope (IMPORTANT)

The Eshway outreach skill is **ONLY for Instagram DM / message copy generation**.

- Canonical: `backend-automation/skills/eshway_client_outreach_skill.md`
- Mirror: `docs/eshway_client_outreach_skill.md`
- Fragment: `linkedin/templates/prompts/eshway_dm_messaging_skill.j2`
- Wired into: `follow_up_agent.j2` (+ draft regenerate via `run_follow_up_agent`)
- **Not** wired into search/qualify as the whole workflow

Discovery / qualify use campaign `product_docs` + `campaign_objective` (website-dev + agency ICP). See `backend-automation/defaults/`.

## Full automation loop

1. **Search** — keywords / candidate pools
2. **Qualify** — ML + LLM gate (CLIENT / COLLABORATION ICP)
3. **HITL DM draft** — immediately after qualify (no Follow / follow-back gate)
4. **Approve → send** — operator approves in Messages; Playwright sends Instagram DM
5. **Reply** — ingest prospect replies
6. **Follow-up** — bumps when no reply (after messaging)
7. **Export** — Sheets / CRM export (`message_sent` or legacy follow-back verification)

The skill only governs **wording** of DMs in steps 3–6.

**DM-first note:** Instagram allows direct messaging without following. If the
Message button is missing (private/restricted), the deal is marked Failed with
a clear reason — we do **not** fall back to Follow.

## How to run

```bash
./run-dev.sh              # API :8000 + Frontend :3000
./run-dev.sh --daemon     # also rundaemon (after migrate)

cd backend-automation && source .venv/bin/activate
python manage.py migrate
python manage.py setup_crm
python manage.py createsuperuser   # staff login for UI + /admin/
# or: python manage.py create_admin_user <instagram_username>
python manage.py runserver
python manage.py rundaemon
```

## Required env vars (`backend-automation/.env`)

| Variable | Required | Notes |
|----------|----------|-------|
| `SUPABASE_URL` | **Yes** | Postgres URL (no SQLite fallback) |
| `DEBUG` | Local | `true` for local |
| `ALLOWED_HOSTS` | Yes | e.g. `127.0.0.1,localhost` |
| `LEADPILOT_ENCRYPTION_KEY` | Prod | Encrypts Instagram passwords (≥32 bytes) |
| `BOT_TIME_LIMITS_ENABLED` | Optional | Quotas / active hours |
| `BOT_SLEEP_ENABLED` | Optional | Human-like delays |
| `BOT_ACTIVE_HOURS_ENABLED` | Optional | Pause outside window |
| `PLAYWRIGHT_HEADLESS` | Optional | `1` on servers without display |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Sheets | OAuth for export |
| `GOOGLE_REDIRECT_BASE` | Sheets | e.g. `http://127.0.0.1:8000` |

LLM keys live in **Site Config** (DB / UI).

## Schema / migrations

```bash
cd backend-automation && source .venv/bin/activate
python manage.py migrate
```

Key migrations:

| Migration | What |
|-----------|------|
| `linkedin.0021_instagram_conversion` | `LinkedInProfile` → `InstagramProfile`; columns `instagram_*` / `follow_*`; `pause_new_follows` |
| `linkedin.0022_rename_instagram_profile_table` | Physical table `linkedin_linkedinprofile` → `linkedin_instagramprofile` |
| `linkedin.0023_rename_after_invite_confidence` | `sheet_export_min_confidence_after_follow` |
| `crm.0009_instagram_fields` | `Lead.instagram_url` |
| `crm.0010_instagram_follow_fields` | `follow_attempts`, `follow_assessment_*` |
| `chat.0007_instagram_fields` | `instagram_profile` / `instagram_message_id` |

## API

| Endpoint | Notes |
|----------|-------|
| `/api/instagram-profiles/` | Canonical (create/list) |
| `/api/instagram-profiles/<id>/` | Delete |
| `/api/instagram-profiles/<id>/toggle/` | Toggle active |
| Safety | `pauseNewFollows` = pause new outreach expansion (discover/qualify/drafts) |

Legacy `/api/linkedin-profiles/` aliases are **removed**.

## Intentional leftovers (minimize; honest)

| Leftover | Why |
|----------|-----|
| Django app package / `app_label` `linkedin/` | Renaming rewrites migration history + every import; product is Instagram |
| Historical migration *filenames* / old ops | Immutable once applied |
| Sheet helpers accept legacy `linkedin.com/in\|pub` cells + “LinkedIn Profile” headers | Optional backward compat for old spreadsheets only |
| Brevo newsletter form field key `LINKEDIN` | Hosted form schema; value is Instagram URL |
| `OnboardConfig.from_json` maps legacy `linkedin_email` → `instagram_username` | Old onboard JSON files |
| CRM state value `Connected` | Stored pipeline enum (not LinkedIn product copy); UI still shows deal state |
| Module filenames like `tasks/connect.py` | Implement Instagram Follow; renaming modules is optional cleanup |
| `linkedin/api/voyager.py` | Dead stubs only; not on hot path |

## Primary ops blocker

Apply migrations + verify Instagram browser login/session before trusting the full loop.

Full checkbox list: [`docs/TESTING_CHECKLIST.md`](docs/TESTING_CHECKLIST.md).
