"""Rebuild ONE sheet tab with verification-gated rows only (e.g. Sheet 2).

Does not read or modify any other tab. Blocks Sheet1 by default.

The Sheets API needs the **exact** tab title as Google stores it, or ``--sheet-gid``
from the browser URL (``...#gid=610279427`` → use ``--sheet-gid 610279427``).

Example::

    python manage.py rebuild_verified_sheet_tab --tab \"Sheet 2\" --dry-run
    python manage.py rebuild_verified_sheet_tab --sheet-gid 610279427 --dry-run
    python manage.py rebuild_verified_sheet_tab --tab \"Sheet 2\"

Set ``SiteConfig.google_sheet_id`` (or pass ``--spreadsheet-id``) and ensure
Google OAuth is connected for the sync user. Point automated CRM exports at
the same tab via ``SiteConfig.google_sheet_tab`` so Sheet 1 stays manual-only.
"""
from django.core.management.base import BaseCommand, CommandError
from googleapiclient.errors import HttpError

from google_integration.sheet_cleanup import rebuild_verified_tab_only
from google_integration.spreadsheet_id import normalize_spreadsheet_id
from linkedin.models import SiteConfig

# lead_sheet_export_verification() reason_code → short hint for operators
VERIFICATION_REASON_HINTS: dict[str, str] = {
    "not_connected": "no Deal in CONNECTED state for this lead",
    "no_connection_detected_event": "no OutreachEvent with type connection_detected",
    "no_invite_for_non_api_path": "detection is not high-confidence API 1st degree; need invite_sent for post-invite path",
    "detection_before_last_invite": "latest connection_detected is older than the last invite_sent",
    "insufficient_confidence_or_source": "confidence or source in event metadata below SiteConfig thresholds",
    "unknown": "unexpected reason code",
}


class Command(BaseCommand):
    help = (
        "Replace data on a single tab with CRM-matched rows. "
        "Default: full export verification (OutreachEvent + confidence). "
        "Use --connected-only (Connected deal only) or --pipeline-only "
        "(Qualified / Pending / Connected deals; drops failed-only / no-deal noise). "
        "Does not touch other tabs. Use --sheet-gid from the URL if --tab fails."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tab",
            default="",
            help='Target tab name (e.g. "Sheet 2"). Matched to API metadata; optional if --sheet-gid is set.',
        )
        parser.add_argument(
            "--sheet-gid",
            type=int,
            default=None,
            help="Sheet id from the spreadsheet URL hash (e.g. #gid=610279427 → 610279427). "
            "Use this if you get 'Unable to parse range' for --tab.",
        )
        parser.add_argument(
            "--spreadsheet-id",
            default="",
            help="Override spreadsheet id; default uses SiteConfig.google_sheet_id",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count drops/keeps only; do not write to Google Sheets",
        )
        parser.add_argument(
            "--force-unsafe-tab",
            action="store_true",
            help="Allow modifying Sheet1-named tabs (dangerous)",
        )
        ex = parser.add_mutually_exclusive_group()
        ex.add_argument(
            "--connected-only",
            action="store_true",
            help="Only require a CRM Deal in Connected state (skip OutreachEvent / confidence export gate).",
        )
        ex.add_argument(
            "--pipeline-only",
            action="store_true",
            help="Keep leads with any Deal in Qualified, Pending, or Connected (remove inactive CRM noise).",
        )

    def handle(self, *args, **options):
        tab = (options["tab"] or "").strip() or None
        sheet_gid = options["sheet_gid"]
        if not tab and sheet_gid is None:
            raise CommandError("Provide --tab and/or --sheet-gid (from the URL #gid=...).")

        cfg = SiteConfig.load()
        sid = (options["spreadsheet_id"] or "").strip() or (cfg.google_sheet_id or "")
        sid = normalize_spreadsheet_id(sid)
        if not sid:
            raise CommandError("No spreadsheet id — set SiteConfig.google_sheet_id or pass --spreadsheet-id")

        self.stdout.write(
            "Connecting to Google Sheets (token refresh happens here if the access token expired)…"
        )
        try:
            stats = rebuild_verified_tab_only(
                spreadsheet_id=sid,
                tab=tab,
                sheet_gid=sheet_gid,
                dry_run=bool(options["dry_run"]),
                force_unsafe_tab=bool(options["force_unsafe_tab"]),
                connected_only=bool(options["connected_only"]),
                pipeline_only=bool(options["pipeline_only"]),
            )
        except ValueError as e:
            raise CommandError(str(e)) from e
        except RuntimeError as e:
            raise CommandError(str(e)) from e
        except HttpError as e:
            err = str(e)
            if "parse range" in err.lower() or e.resp.status == 400:
                raise CommandError(
                    f"Google rejected the range ({err}). "
                    "Try: python manage.py rebuild_verified_sheet_tab --sheet-gid <N> --dry-run "
                    "where <N> is the gid from your spreadsheet URL (#gid=...).",
                ) from e
            raise CommandError(f"Google API error: {err}") from e

        self.stdout.write(self.style.SUCCESS(f"Resolved tab (exact title): {stats['tab']}"))
        if stats.get("tab_requested"):
            self.stdout.write(f"Tab argument was: {stats['tab_requested']!r}")
        if stats.get("sheet_gid_requested") is not None:
            self.stdout.write(f"Sheet gid: {stats['sheet_gid_requested']}")
        self.stdout.write(f"Spreadsheet: {stats['spreadsheet_id']}")
        self.stdout.write(f"Dry run: {stats['dry_run']}")
        self.stdout.write(f"Mode: {stats.get('mode', 'export_verified')}")
        if stats.get("instagram_column_letter") is not None:
            det = stats.get("instagram_detection") or ""
            self.stdout.write(
                f"Instagram URL column: {stats['instagram_column_letter']} "
                f"(index {stats.get('instagram_column_index')}) [{det}]"
            )
        self.stdout.write(f"Data rows read (excl. header): {stats['rows_read']}")
        self.stdout.write(
            f"URLs recovered by scanning the row for instagram.com "
            f"(legacy linkedin.com cells still accepted): {stats.get('urls_from_row_scan_fallback', 0)}"
        )
        self.stdout.write(f"Kept (written): {stats['kept']}")
        self.stdout.write(f"Dropped — empty URL: {stats['dropped_no_url']}")
        self.stdout.write(f"Dropped — URL not in CRM: {stats['dropped_no_lead']}")
        self.stdout.write(f"Dropped — no CRM deals at all: {stats.get('dropped_no_deals', 0)}")
        if stats.get("connected_only"):
            self.stdout.write(f"Dropped — not connected (no CONNECTED deal): {stats.get('dropped_not_connected', 0)}")
        elif stats.get("pipeline_only"):
            self.stdout.write(
                f"Dropped — not in pipeline (only Failed/Completed deals): "
                f"{stats.get('dropped_not_in_pipeline', 0)}"
            )
        else:
            self.stdout.write(f"Dropped — failed verification: {stats['dropped_not_verified']}")
            reject_map = stats.get("verification_reject_counts") or {}
            if reject_map:
                self.stdout.write("")
                self.stdout.write("Failed verification — breakdown by reason:")
                for code, n in reject_map.items():
                    hint = VERIFICATION_REASON_HINTS.get(code, "")
                    if hint:
                        self.stdout.write(f"  {n:5d}  {code}  —  {hint}")
                    else:
                        self.stdout.write(f"  {n:5d}  {code}")
            if stats["kept"] == 0 and stats.get("dropped_not_verified", 0) > 0:
                self.stdout.write(
                    self.style.WARNING(
                        "Note: failed verification = lead_sheet_export_verification "
                        "(CONNECTED + connection_detected event + confidence rules). "
                        "Use --pipeline-only or --connected-only for looser gates."
                    )
                )
        self.stdout.write(f"Dropped — duplicate URL rows: {stats['duplicate_urls_collapsed']}")
