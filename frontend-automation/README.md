# Leadway Next.js Frontend — Instagram Outreach

Operator UI for Leadway Instagram automation (Eshway website-dev + agency collab campaigns).

## Stack

- Next.js App Router + Tailwind
- Typed API client with backend proxy (`/api/backend/*`)

## Features

- Login via Django staff credentials
- Dashboard, campaigns, leads, deals, tasks
- Instagram profiles (credentials + limits)
- HITL message drafts + batch approve (DM copy from messaging skill on backend)
- Google Workspace / Sheets
- Daemon controls

## Messaging skill note

UI does not embed the outreach skill. Backend draft/regenerate endpoints use `skills/eshway_client_outreach_skill.md` for **Instagram DM wording only**. Search/qualify stay ICP-driven.

## Local run

### 1) Backend (repo)

```bash
cd ../backend-automation
source .venv/bin/activate
python manage.py migrate    # Instagram schema — required
python manage.py runserver
# optional worker:
python manage.py rundaemon
```

### 2) Frontend

```bash
cd frontend-automation
# optional: cp .env.local.example .env.local when present
npm install
npm run dev
```

Or from monorepo root: `./run-dev.sh` / `./run-dev.sh --daemon`

Open [http://localhost:3000](http://localhost:3000).

## API

Profile routes: `/api/instagram-profiles/`.

See [`../INSTAGRAM_CONVERSION_NOTES.md`](../INSTAGRAM_CONVERSION_NOTES.md) and [`../docs/TESTING_CHECKLIST.md`](../docs/TESTING_CHECKLIST.md).
Phased testing can start after backend `migrate`; live E2E still needs a real Instagram session.
