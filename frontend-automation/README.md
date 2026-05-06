# Leadway Next.js Frontend

This is a full frontend rebuilt in Next.js + Tailwind and connected to the Django backend.

## Stack

- Next.js App Router
- Tailwind CSS
- Typed API client
- Backend proxy route (`/api/backend/*`) to forward cookies/session to Django

## Features Implemented

- Login/logout using Django staff credentials
- Dashboard stats
- Campaign listing
- Leads table with search/state filter
- Deals table
- Task queue view
- HITL message drafts + batch approve action
- Google Workspace page (embedded + open in new tab)

## Backend API Added (Django)

The frontend consumes these Django JSON endpoints:

- `/api/csrf/`
- `/api/auth/login/`
- `/api/auth/logout/`
- `/api/auth/me/`
- `/api/dashboard/`
- `/api/campaigns/`
- `/api/leads/`
- `/api/deals/`
- `/api/tasks/`
- `/api/messages/drafts/`
- `/api/messages/drafts/approve/`

## Local Run

### 1) Start Django backend (repo root)

```bash
source .venv/bin/activate
python manage.py runserver
```

### 2) Start Next.js frontend (`Automation_frontend`)

```bash
cd Automation_frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Notes

- The frontend uses Django session auth; login is handled through `/api/auth/login/`.
- For production, set `BACKEND_BASE_URL` and `NEXT_PUBLIC_BACKEND_URL` in `.env.local`.
