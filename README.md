# Leadway — Instagram outreach (Eshway)

Monorepo for Leadway: Instagram discovery → qualify → follow → HITL DM → reply → follow-up → Sheets export, aimed at **website development clients** and **agency collaborations** for Eshway.

## Status: READY FOR TESTING (after migrate)

Hot path is Instagram-only (`instagram.com` search / follow / DM). Apply migrations before daemon or E2E.

| Ready | Validate live |
|-------|----------------|
| Operator UI (Instagram copy) | Instagram login / 2FA / challenge (headed Playwright) |
| Messaging skill (DM copy **only**) | Fragile IG selectors (TODO markers in `actions/`) |
| `/api/instagram-profiles/` (no LinkedIn path aliases) | Live follow / DM / reply loop |
| Sheets header “Instagram Profile” | Optional legacy sheet cells still accepted |
| Models / columns / profile table Instagram-named | — |

Details: [`INSTAGRAM_CONVERSION_NOTES.md`](INSTAGRAM_CONVERSION_NOTES.md)  
Testing: [`docs/TESTING_CHECKLIST.md`](docs/TESTING_CHECKLIST.md)

## Messaging skill (DM wording only)

- [`docs/eshway_client_outreach_skill.md`](docs/eshway_client_outreach_skill.md)
- [`backend-automation/skills/eshway_client_outreach_skill.md`](backend-automation/skills/eshway_client_outreach_skill.md)

Use **only** for Instagram DM generation. Search/qualify use campaign ICP docs — do not treat the skill as the workflow.

## Layout

- `backend-automation/` — Django + Playwright daemon
- `frontend-automation/` — Next.js operator UI
- `docs/` — skill mirror + testing checklist

## Dev

```bash
./run-dev.sh          # backend :8000 + frontend :3000
./run-dev.sh --daemon # also rundaemon
```

Before any DB / daemon work:

```bash
cd backend-automation && source .venv/bin/activate
python manage.py migrate
python manage.py setup_crm
python manage.py createsuperuser   # required once — staff login for the UI
```

**Note:** Django app package folder remains `linkedin/` for import/migration stability; product language, APIs, and automation are Instagram.
