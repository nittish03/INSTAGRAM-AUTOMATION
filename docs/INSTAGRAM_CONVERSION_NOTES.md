# Instagram conversion notes

**Status: READY FOR TESTING after `migrate`.**

Hot-path code targets Instagram (search/qualify/DM). Follow/check_pending are
dormant; product path is DM-first after qualify. LinkedIn Voyager and
`/api/linkedin-profiles/` aliases are removed from the product surface. Run
migrations, then use `docs/TESTING_CHECKLIST.md`.

## Messaging skill scope (IMPORTANT)

The Eshway outreach skill is **ONLY for Instagram DM / message copy generation**.

- Canonical: `backend-automation/skills/eshway_client_outreach_skill.md`
- Mirror: `docs/eshway_client_outreach_skill.md`
- Fragment (optional): `linkedin/templates/prompts/eshway_dm_messaging_skill.j2`
- Wired into: `follow_up_agent.j2` (+ draft regenerate via `run_follow_up_agent`)
- **Not** wired into search/qualify as the whole workflow

Discovery / qualify use campaign `product_docs` + `campaign_objective` (website-dev + agency ICP). See `backend-automation/defaults/`.

## Full automation loop

1. **Search** — keywords / candidate pools
2. **Qualify** — ML + LLM gate (CLIENT / COLLABORATION ICP)
3. **HITL DM draft** — immediately after qualify (no Follow / follow-back gate)
4. **Approve → send** — operator approves; Playwright sends Instagram DM
5. **Reply** — ingest prospect replies
6. **Follow-up** — bumps when no reply (after messaging)
7. **Export** — Sheets / CRM export (`message_sent` or legacy follow-back)

The skill only governs **wording** of DMs in steps 3–6.

**DM-first:** If Message is unavailable (private/restricted), deal is Failed — no Follow fallback.

## How to run

```bash
./run-dev.sh              # API :8000 + Frontend :3000
./run-dev.sh --daemon     # also rundaemon (after migrate)

cd backend-automation && source .venv/bin/activate
python manage.py migrate
python manage.py setup_crm
```

## Required env vars (`backend-automation/.env`)

| Variable | Required | Notes |
|----------|----------|-------|
| `SUPABASE_URL` | **Yes** | Postgres URL (no SQLite fallback) |
| `DEBUG` | Local | `true` for local |
| `ALLOWED_HOSTS` | Yes | e.g. `127.0.0.1,localhost` |
| `LEADPILOT_ENCRYPTION_KEY` | Prod | Encrypts Instagram passwords (≥32 bytes) |
| `BOT_TIME_LIMITS_ENABLED` | Optional | Quotas / active hours |
| `PLAYWRIGHT_HEADLESS` | Optional | `1` on servers without display |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Sheets | OAuth for export |
| `GOOGLE_REDIRECT_BASE` | Sheets | e.g. `http://127.0.0.1:8000` |

LLM keys live in **Site Config** (DB / UI).

## What is ready

| Area | State |
|------|--------|
| Frontend operator UI | Instagram-only (no LinkedIn path fallbacks) |
| Messaging skill + DM prompts | Done (messaging-only) |
| `/api/instagram-profiles/` | Canonical only |
| DB migrations through `0023` / `crm.0010` / `chat.0007` | Apply before E2E |
| Playwright Instagram search/follow/DM hot path | Ready after migrate + session |
| Sheets headers | “Instagram Profile” (legacy LinkedIn header/cell optional accept) |

## Intentional leftovers

| Leftover | Why |
|----------|-----|
| Django app package `linkedin/` | Import + migration history stability |
| Historical migration filenames | Immutable |
| Sheet legacy LinkedIn URL/header detection | Optional backward compat only |
| Brevo form field key `LINKEDIN` | Hosted form schema |
| Module names `tasks/connect.py` | Instagram Follow implementation |
| `voyager.py` stubs | Dead; not hot path |
| CRM enum value `Connected` | Stored deal state string |

Do not run the daemon against a DB that still has pre-0021 LinkedIn column names.
