# Leadway / Eshway: Instagram Outreach Automation

Instagram outreach system for Eshway — lead discovery, qualification, follow + HITL DMs — Django + Playwright daemon.

## What it does

1. **Discovery** — Instagram search / hashtags → enrich profiles → lead pool
2. **Qualification** — ML + LLM gate for website-dev clients and agency collaborations
3. **Follow** — conservative follow pacing with rate limits / active hours
4. **Follow-back check** — detect Message availability / follow-back
5. **Messaging (HITL)** — draft DMs with the Eshway outreach messaging skill → operator approve → send
6. **Reply sync + follow-ups** — reply_check / follow_up task loop

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/local.txt
playwright install chromium

# .env must include SUPABASE_URL (Postgres), optional GOOGLE_* and LEADPILOT_ENCRYPTION_KEY
python manage.py migrate
python manage.py setup_crm
python manage.py createsuperuser
```

## Run

```bash
# API / admin
python manage.py runserver

# Automation worker
python manage.py rundaemon
```

## Instagram API surface (frontend)

- `GET|POST /api/instagram-profiles/`
- `DELETE /api/instagram-profiles/<id>/`
- `POST /api/instagram-profiles/<id>/toggle/`
- Leads expose `instagramUrl` + `username` (`publicIdentifier`)
- Drafts / approve / regenerate remain under `/api/messages/...`

## Notes

- Django app package remains `linkedin/` internally; product language and automation are Instagram.
- DMs are **never** auto-sent — HITL approval required.
- Instagram UI selectors are fragile; see TODOs in `linkedin/actions/` and `linkedin/browser/`.
