# Instagram Leadway — Testing Checklist

**Pre-req:** `cd backend-automation && source .venv/bin/activate && python manage.py migrate`

Use this after the Instagram conversion. Mark items during live E2E.

## A. Bootstrap

- [ ] `migrate` succeeds (linkedin 0021–0023, crm 0009–0010, chat 0007)
- [ ] `setup_crm` seeds Instagram campaign defaults when empty
- [ ] `.env` has `SUPABASE_URL`; optional Google + encryption key
- [ ] `./run-dev.sh` brings API `:8000` + FE `:3000`

## B. Operator UI (copy)

- [ ] Nav / pages say Instagram (profiles, follows, DMs) — no LinkedIn labels
- [ ] `/instagram-profiles` create/list/toggle works
- [ ] `/linkedin-profiles` is gone (404)
- [ ] Safety: `pauseNewFollows` (“Pause new outreach”) toggles and persists
- [ ] Leads show `instagramUrl` links to `instagram.com`
- [ ] Messages UI is Instagram DM / HITL (drafts for Qualified, not follow-gated)
- [ ] Deals show `followAttempts` (legacy field; not required for DM path)

## C. API

- [ ] `GET/POST /api/instagram-profiles/` works
- [ ] `DELETE` + `toggle` under `/api/instagram-profiles/<id>/`
- [ ] `GET /api/linkedin-profiles/` returns 404 (aliases removed)
- [ ] Site config / safe-mode exposes `pauseNewFollows` only

## D. Sheets

- [ ] New rows use header **Instagram Profile** / **Followed**
- [ ] Export uses Instagram URLs
- [ ] (Optional) Old sheets with “LinkedIn Profile” header still resolve

## E. Daemon loop (headed first login OK)

- [ ] Login / session against Instagram
- [ ] Search finds Instagram accounts
- [ ] Qualify gates CLIENT / COLLABORATION
- [ ] After qualify, DM draft appears in Messages **without** Follow / Connected
- [ ] Approve → `send_message` opens profile Message button and sends DM
- [ ] If Message button missing (private/restricted): deal Failed, no auto-Follow
- [ ] Reply check + follow-up bumps **after** send
- [ ] Safety “Pause new outreach” stops discover/qualify expansion only

## F. Messaging skill

- [ ] Drafts follow Eshway DM skill tone (not LinkedIn connect language)
- [ ] Skill not incorrectly pasted into search/qualify prompts

## Known flake (not conversion blockers)

| Item | Notes |
|------|--------|
| IG Message / composer selectors | TODOs in `actions/message.py` |
| Challenges / 2FA | Complete once in headed browser |
| Sheet legacy cell scan | Optional LinkedIn URL accept for old sheets only |
| Private accounts | Message button may be absent — expected Failed path |

**READY FOR TESTING** when A–C pass locally; full confidence needs E live.
