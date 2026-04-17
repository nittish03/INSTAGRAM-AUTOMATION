# LeadPilot Comprehensive System Documentation

This document explains the entire web app in depth: what it does, why it exists, how it works, and how its workflows move data across the system.

---

## 1) Product Purpose and Why This Exists

LeadPilot is a Django-based LinkedIn outreach automation platform with human-in-the-loop controls.

The system is designed to:
- Discover and qualify LinkedIn prospects at scale.
- Manage campaign-specific pipeline state in a CRM model.
- Automate operational steps (connect checks, follow-ups, scheduling).
- Keep final outbound message control with a human approver in admin.

In practical terms, it blends:
- **Automation engine** (daemon + task queue),
- **Operator console** (Django admin with Unfold),
- **Decision intelligence** (LLM + ML qualifier),
- **Data persistence** (Django ORM over Supabase Postgres only).

---

## 2) High-Level Architecture

### 2.1 Control Plane vs Worker Plane

1. **Control plane (web/admin):**
   - Django Admin at `/admin/`
   - Unfold-based dashboard and custom admin actions
   - Models edited/reviewed by operators

2. **Worker plane (background runtime):**
   - `rundaemon` management command
   - Database-backed task queue (`linkedin.Task`)
   - Single-thread loop dispatching task handlers

### 2.2 Core Apps

- `linkedin`: orchestration, automation, queues, API clients, models for campaign/profile/task/action logs, daemon, settings, admin.
- `crm`: lead/deal domain models and CRM-focused admin UI.
- `chat`: conversation/draft persistence with moderation flags.

### 2.3 Entry Points

- `manage.py` defaults to `rundaemon` if called without args.
- Common runtime commands:
  - `python manage.py runserver`
  - `python manage.py rundaemon`
  - `python manage.py migrate`
  - `python manage.py onboard`
  - `python manage.py setup_crm`

---

## 3) Routing and UI Surface

URL routing is intentionally minimal:
- `/admin/` is the main application UI.
- No general front-end pages are exposed at `/`.
- No broad public API routes are declared in Django URLconf.

The primary user interaction model is admin-driven operations:
- pipeline review,
- draft approval,
- imports,
- monitoring.

---

## 4) Configuration Model

### 4.1 Django Settings Model

`linkedin/django_settings.py` controls:
- installed apps and middleware,
- DB engine selection:
  - Postgres only via required `SUPABASE_URL`,
  - no SQLite/local fallback,
- static/media paths,
- logging setup,
- Unfold dashboard callback wiring.

### 4.2 Environment Behavior

Important behavior:
- `DEBUG` defaults to false if not set.
- In non-debug mode, `ALLOWED_HOSTS` must be set.
- In production, `DJANGO_SECRET_KEY` must be set.

Operational implication:
- local setup often requires `DEBUG=true` unless full production env vars are provided.
- if `.env` is missing or DB URL is absent/invalid, startup fails immediately.

### 4.3 Campaign/Runtime Constants

`linkedin/conf.py` holds:
- active-hours scheduling rules,
- campaign timing defaults,
- embedding model identifier,
- browser automation timing constants.

---

## 5) Data Model (Full Domain)

## 5.1 Auth and Profile Layer

### `User` (Django auth)
- Operator/account identity.

### `LinkedInProfile` (`linkedin.models`)
- One-to-one with `User`.
- Stores LinkedIn username/password, cookie state, legal acceptance, rate limits, active status.
- Optional `self_lead` pointer into `crm.Lead`.
- Password encrypted at rest.

Purpose:
- Represents the account that executes automation and owns LinkedIn session context.

## 5.2 Campaign and Queue Layer

### `Campaign`
- Campaign metadata: objective, docs, booking link, freemium toggle, user assignments.
- Owns deals, search keywords, and action logs.
- Persists/loads campaign ML model from filesystem (`models/campaign_<id>.joblib`).

### `SearchKeyword`
- Campaign-scoped keyword bank.
- Tracks usage state for search prompt outputs.

### `Task`
- DB queue unit with:
  - `task_type`: connect/check_pending/follow_up/send_message
  - `status`: pending/running/completed/failed/skipped
  - schedule and payload
  - optional direct `deal` FK
- Includes helper query APIs (`pending`, `due`, `claim_next`, `seconds_to_next`).

### `ActionLog`
- Tracks outbound action events (connect/follow_up).
- Contains target metadata and status/note.
- Used for daily/weekly rate-limit enforcement and dashboard metrics.

### `SiteConfig`
- Singleton for LLM credentials and model/base settings.
- API key encrypted at rest.

## 5.3 CRM Layer

### `Lead` (`crm.models.lead`)
- Global person identity:
  - unique `linkedin_url`,
  - unique `public_identifier`,
  - profile snapshot JSON,
  - embedding bytes.
- `disqualified` means permanent global ban across all campaigns.

### `Deal` (`crm.models.deal`)
- Campaign-scoped pipeline instance for a lead.
- Unique per (`lead`, `campaign`).
- Holds state, closure reason, qualification reason, attempts, backoff.

Relationship summary:
- `Campaign` 1..* `Deal`
- `Lead` 1..* `Deal`
- `Deal` 1..* `Task`
- `LinkedInProfile` 1..* `ActionLog`
- `Campaign` 1..* `ActionLog`

## 5.4 Chat Layer

### `ChatMessage`
- Conversation records + AI draft artifacts.
- Uses generic FK (content type + object id).
- Stores LinkedIn message URN for deduplication.
- Moderation flags:
  - `is_draft`
  - `is_approved`

Purpose:
- Supports human review/approval before send actions are executed.

---

## 6) State Machines and Pipeline Semantics

## 6.1 Deal/Profile State Enum

`ProfileState`:
- `Qualified`
- `Pending`
- `Connected`
- `Completed`
- `Failed`

Typical transitions:
- `Qualified -> Pending -> Connected -> Completed`
- failure branches move to `Failed`.

## 6.2 Task State Machine

Task execution state:
- `pending -> running -> completed|failed|skipped`

This state machine is maintained by daemon handler execution wrappers.

---

## 7) End-to-End Operational Workflow

## 7.1 Startup Sequence

`rundaemon` command flow:
1. Run migrations.
2. Run CRM bootstrap.
3. Validate onboarding completeness (interactive/non-interactive path).
4. Ensure active LinkedIn profile + LLM config.
5. Start daemon queue loop.

## 7.2 Daemon Queue Loop

`linkedin/daemon.py`:
1. Build qualifiers per campaign (Bayesian or freemium kit).
2. Heal queue on startup:
   - recover stale running tasks,
   - seed connect tasks,
   - seed pending checks/follow-ups as needed.
3. Enforce active-hours schedule.
4. Claim due task, dispatch handler by task type.
5. Mark task completed/skipped/failed based on outcome.

## 7.3 Lead Discovery and Enrichment

Search pipeline:
1. Generate/select keyword.
2. Search LinkedIn profiles.
3. Extract `/in/...` URLs.
4. Normalize/store unknown leads.
5. Enrich lead profile via Voyager API.
6. Compute/store embeddings.

## 7.4 Qualification Logic

Two strategy paths:
- **Regular campaigns:** Bayesian qualifier + LLM decision support.
- **Freemium campaigns:** pre-trained kit model ranking.

Qualification creates or updates deal state:
- accepted -> move into actionable pipeline,
- rejected -> campaign-specific fail/disqualification reason.

## 7.5 Connect and Pending Monitoring

Connect task:
- checks account rate limits,
- selects next candidate,
- determines current relationship status,
- sends invite when valid,
- logs action and reschedules.

Pending-check task:
- rechecks relationship state over time,
- applies exponential backoff with jitter,
- closes stale long-pending deals.

## 7.6 Follow-Up and HITL Messaging

Follow-up task:
- syncs/reads conversation context,
- invokes follow-up agent,
- one of:
  - create draft (`is_draft=True`),
  - wait and reschedule,
  - mark deal completed.

Human approval path:
- admin action approves draft and enqueues `send_message`.

Send-message task:
- sends via UI/API strategy,
- logs follow-up action,
- schedules next follow-up where applicable.

---

## 8) LinkedIn Integration Internals

## 8.1 Browser Automation Stack

- Playwright with stealth plugin.
- Session abstraction manages browser/context/page lifecycle.
- Login supports cookie reuse and credential fallback.
- Cookie state persisted in DB.

## 8.2 Voyager API Access Pattern

API calls are executed in browser context using page `fetch`:
- preserves browser cookies/session naturally,
- pulls CSRF token from session cookies.

Capabilities include:
- profile data retrieval,
- messaging conversation retrieval/sync,
- fallback message send.

---

## 9) AI/ML Subsystem

## 9.1 Embeddings

- FastEmbed model (`BAAI/bge-small-en-v1.5`) generates vectors.
- vectors stored in `Lead.embedding`.

## 9.2 Bayesian Qualifier

- Uses Gaussian Process Regression + uncertainty-driven selection.
- Warm-starts from labeled deal history.
- Supports explore/exploit candidate prioritization.

## 9.3 Freemium Kit Path

- Loads pre-trained campaign kit model (Hugging Face backed artifact flow).
- Used when campaign `is_freemium=True`.

## 9.4 Prompting

Jinja templates define structured LLM tasks:
- lead qualification,
- keyword generation,
- follow-up decisioning.

---

## 10) Admin and Operator Experience

Admin UI is heavily customized and operationally central:
- custom list views, filters, readonly insights,
- import/export workflows,
- deal requeue/force-requalify actions,
- draft approval and send orchestration,
- history/audit displays via simple-history.

This app is effectively an operations console, not a public web app.

---

## 11) Security, Compliance, and Safety Controls

### Strengths
- Encryption at rest for key sensitive fields.
- Production guardrails for missing secret/hosts.
- HITL gate for outbound generated messaging.
- Account-level daily/weekly send limits.

### Caveats
- Security hardening flags for production transport/cookies should be reviewed (SSL redirect, HSTS, secure cookies).
- CORS can be globally relaxed by env.
- Supabase Postgres is now mandatory for all environments in this codebase.

---

## 12) Observability and Failure Handling

- Rotating file + console logging configured.
- Daemon diagnostics wrapper captures runtime failures.
- Task failure tracebacks stored in task error field.
- Startup queue healing improves crash recovery.

---

## 13) Tests and Coverage Reality

Current tests cover important core pieces:
- model encryption behavior,
- task state methods,
- selected task/daemon behavior.

Coverage gaps remain in:
- full browser automation E2E,
- real API response-shape integration,
- onboarding non-interactive edge paths,
- full admin approve-and-send end-to-end execution.

---

## 14) Known Risk/Consistency Watchlist

The codebase shows a few areas to verify/fix during hardening:
- Potential response-shape mismatches between messaging conversation API and parser.
- Seed parsing function references that may not align in all command paths.
- Onboarding non-interactive argument/schema mismatches.
- Dashboard callback bug class (like the `today`/`last_week` issue) indicates need for regression checks around computed dashboard context.

---

## 15) Why This Design Works

This architecture works well for the stated use case because:
- It keeps the operator in control for final messaging decisions.
- It uses deterministic DB-backed queueing with transparent state.
- It combines probabilistic ranking (ML) with contextual judgment (LLM).
- It centralizes all operational controls in one admin console.

The tradeoff is that reliability depends on:
- strict schema/API consistency,
- robust session handling against platform changes,
- disciplined testing around automation and parser contracts.

---

## 16) Practical Mental Model for New Developers

If you are onboarding to this codebase, think in this order:
1. **Models first** (`Lead`, `Deal`, `Task`, `ActionLog`, `ChatMessage`).
2. **Queue semantics second** (how `Task` gets enqueued, claimed, and completed).
3. **Handler flow third** (`connect`, `check_pending`, `follow_up`, `send_message`).
4. **Only then** inspect browser/API integration internals and qualifier math.

This sequence matches how failures usually manifest in production:
- state mismatch -> queue oddities -> handler behavior -> integration specifics.

---

## 17) File Index (Key Areas)

- Runtime and config:
  - `manage.py`
  - `linkedin/django_settings.py`
  - `linkedin/conf.py`
  - `linkedin/daemon.py`
- Domain:
  - `linkedin/models.py`
  - `crm/models/lead.py`
  - `crm/models/deal.py`
  - `chat/models.py`
- Task handlers:
  - `linkedin/tasks/connect.py`
  - `linkedin/tasks/check_pending.py`
  - `linkedin/tasks/follow_up.py`
  - `linkedin/tasks/send_message.py`
- Pipelines and ML:
  - `linkedin/pipeline/search.py`
  - `linkedin/pipeline/qualify.py`
  - `linkedin/pipeline/pools.py`
  - `linkedin/pipeline/freemium_pool.py`
  - `linkedin/ml/qualifier.py`
  - `linkedin/ml/embeddings.py`
- Integrations:
  - `linkedin/browser/session.py`
  - `linkedin/browser/login.py`
  - `linkedin/api/client.py`
  - `linkedin/api/voyager.py`
  - `linkedin/api/messaging/*`
- Admin/UI:
  - `linkedin/admin.py`
  - `crm/admin.py`
  - `linkedin/views.py`
  - `linkedin/urls.py`

---

## 18) Migration and Infra Change Log

### 18.1 Supabase Shift Iteration (Current)

What was introduced:
- Django DB URL parsing for Supabase/Postgres in `linkedin/django_settings.py`.
- `.env` loading support via `python-dotenv`.
- Added dependencies:
  - `psycopg[binary]`
  - `python-dotenv`

Verification command for future iterations:
- `DEBUG=true python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default'])"`
- Expected for Supabase:
  - `ENGINE = django.db.backends.postgresql`
  - populated `HOST`, `USER`, `PORT`.

Recommended stabilization practice:
- after every infra/config change, run DB engine verification first, then `migrate`, then user/admin operations.

---

### 18.2 Supabase-Only Enforcement Iteration

What changed:
- Removed SQLite fallback from `linkedin/django_settings.py`.
- `SUPABASE_URL` is now required at startup; app raises `ImproperlyConfigured` if missing.
- Removed legacy compatibility key usage (`SUPABSE_URL`) from runtime path.
- Updated setup docs (`README.md`) to make Supabase env configuration mandatory.
- Removed SQLite ignore patterns from `.gitignore` as part of SQLite deprecation.

Behavioral impact:
- Any command (`migrate`, `runserver`, `rundaemon`, etc.) now fails fast if `SUPABASE_URL` is not present.
- This prevents accidental command execution against a local SQLite database.

Operational requirement:
- Ensure `.env` exists in project root with a valid `SUPABASE_URL` before running Django commands.

---

### 18.3 Onboarding Campaign-Link Fix Iteration

Problem observed:
- During onboarding, entering a campaign name did not always result in campaign membership for the current user.
- Daemon then failed at startup with `No campaigns found for this user.`

Root cause:
- Campaign-user linking was tied to `_create_account()`, which only runs when a new `LinkedInProfile` is created.
- If profile already existed, onboarding could skip account creation and skip campaign membership linking.

Fix implemented in `linkedin/onboarding.py`:
- After onboarding campaign resolution, explicitly link campaign to the user resolved from `config.linkedin_email` if that profile exists.
- Added a safe auto-heal path: if campaign has zero users and there is exactly one active LinkedIn profile, auto-link that sole user.

Behavioral impact:
- Re-running onboarding now repairs campaign membership for existing profiles instead of failing daemon startup later.
- Fresh-start flows are more deterministic: campaign input during onboarding now maps to the current operator account in common single-user setups.

---

### 18.4 LinkedIn Login Resilience Iteration

Problem observed:
- Daemon reached LinkedIn login URL but failed with Playwright timeout waiting for `input#username`.
- This blocked automation even with valid stored LinkedIn credentials/profile setup.

Root cause:
- Login automation depended on a single rigid selector set (`input#username`, `input#password`, generic submit button).
- LinkedIn can serve variant login/challenge pages where those exact selectors are absent.

Fix implemented in `linkedin/browser/login.py`:
- Added fallback selector lists for email, password, and submit controls.
- Added challenge/captcha indicator detection.
- Added explicit `AuthenticationError` diagnostics with URL and page title when login controls are not found.

Behavioral impact:
- Existing-profile flows now tolerate common LinkedIn DOM variations.
- Failures are now actionable (`challenge/captcha` vs `missing fields`) instead of generic Playwright timeout traces.

---

### 18.5 SiteConfig Model-Selection Enforcement Iteration

Problem observed:
- Search keyword generation always used a hardcoded model (`gemini-3.1-pro-preview`) regardless of Site Configuration.
- This bypassed operator-selected models and triggered avoidable quota failures on unavailable tiers.

Fix implemented in `linkedin/pipeline/search_keywords.py`:
- Removed hardcoded model override.
- Enforced use of `ai_model` read from Site Configuration.
- Added explicit validation error if `ai_model` is missing.

Behavioral impact:
- Search keyword generation now follows admin-configured model selection exactly.
- Operators can switch model tiers (for example to `gemini-2.5-flash-lite`) without code edits.

---

### 18.6 Search Extraction Reliability Iteration

Problem observed:
- Daemon repeatedly generated keywords and navigated to LinkedIn People search pages but extracted `0` `/in/` profile URLs.
- This caused connect loop churn with periodic sleeps and no candidate discovery.

Root cause:
- Extraction attempted too early on dynamic search pages that lazily render links.
- No retry/scroll cycle existed before deciding there were no profile links.

Fix implemented in `linkedin/actions/search.py`:
- Added `_extract_search_urls_with_retry()`:
  - waits for results container visibility,
  - retries extraction across multiple attempts,
  - performs mouse-wheel scroll to trigger lazy loading,
  - exits early on explicit "No results found".
- `search_people()` now uses this retry-aware extraction path and logs contextual debug when no links are found.

Behavioral impact:
- Search workflows are more robust to delayed or lazy-rendered LinkedIn result pages.
- Reduces false-negative extraction cycles where links exist but were not yet present at first read.

---

This document is a system-level interpretation of current repository behavior and design intent, including operational caveats that are visible from code structure and module contracts.
