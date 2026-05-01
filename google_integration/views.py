"""Google integration views: OAuth + Sheets workspace UI."""
from __future__ import annotations

import json
import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from . import services
from .models import GOOGLE_SCOPES, GoogleAccount
from .oauth import build_flow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redirect_uri(request) -> str:
    return request.build_absolute_uri(reverse("google_integration:callback"))


def _get_account(user) -> GoogleAccount | None:
    return GoogleAccount.objects.filter(user=user).first()


# ---------------------------------------------------------------------------
# Connect / status
# ---------------------------------------------------------------------------

@login_required
def connect(request):
    account = _get_account(request.user)
    return render(
        request,
        "google_integration/connect.html",
        {"account": account},
    )


@login_required
def auth_start(request):
    try:
        flow = build_flow(_redirect_uri(request))
    except ImproperlyConfigured as exc:
        return HttpResponseBadRequest(str(exc))

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["google_oauth_state"] = state
    request.session["google_oauth_code_verifier"] = getattr(flow, "code_verifier", "")
    return redirect(auth_url)


@login_required
def auth_callback(request):
    state = request.session.pop("google_oauth_state", None)
    code_verifier = request.session.pop("google_oauth_code_verifier", "")
    if not state or state != request.GET.get("state"):
        return HttpResponseBadRequest("OAuth state mismatch.")

    if "error" in request.GET:
        messages.error(request, f"Google OAuth error: {request.GET['error']}")
        return redirect("google_integration:connect")

    try:
        flow = build_flow(_redirect_uri(request), state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.build_absolute_uri())
    except Exception as exc:
        logger.exception("Google OAuth token exchange failed")
        messages.error(request, f"Google OAuth failed: {exc}")
        return redirect("google_integration:connect")

    creds = flow.credentials

    google_email = ""
    google_sub = ""
    try:
        if getattr(creds, "id_token", None):
            info = id_token.verify_oauth2_token(
                creds.id_token,
                google_requests.Request(),
                audience=os.environ.get("GOOGLE_CLIENT_ID"),
            )
            google_email = info.get("email", "")
            google_sub = info.get("sub", "")
    except Exception:
        logger.warning("Could not verify id_token; continuing without email", exc_info=True)

    account, _ = GoogleAccount.objects.get_or_create(user=request.user)
    account.google_email = google_email or account.google_email
    account.google_sub = google_sub or account.google_sub
    account.update_from_credentials(creds)
    account.save()

    messages.success(request, f"Google connected as {account.google_email or 'your account'}.")
    return redirect("google_integration:sheets_list")


@login_required
@require_POST
def disconnect(request):
    account = _get_account(request.user)
    if account:
        account.delete()
        messages.info(request, "Google account disconnected.")
    return redirect("google_integration:connect")


# ---------------------------------------------------------------------------
# Sheets workspace
# ---------------------------------------------------------------------------

def _require_account(request):
    account = _get_account(request.user)
    if not account or not account.is_connected:
        messages.warning(request, "Connect your Google account first.")
        return None
    return account


@login_required
def sheets_list(request):
    account = _require_account(request)
    if not account:
        return redirect("google_integration:connect")

    error = None
    spreadsheets: list[dict] = []
    try:
        spreadsheets = services.list_spreadsheets(account)
    except Exception as exc:
        logger.exception("Failed to list spreadsheets")
        error = str(exc)

    return render(
        request,
        "google_integration/sheets_list.html",
        {"account": account, "spreadsheets": spreadsheets, "error": error},
    )


@login_required
@require_POST
def sheets_create(request):
    account = _require_account(request)
    if not account:
        return redirect("google_integration:connect")

    title = (request.POST.get("title") or "").strip() or "Untitled spreadsheet"
    try:
        resp = services.create_spreadsheet(account, title)
    except Exception as exc:
        logger.exception("Failed to create spreadsheet")
        messages.error(request, f"Create failed: {exc}")
        return redirect("google_integration:sheets_list")

    sid = resp.get("spreadsheetId")
    messages.success(request, f"Spreadsheet '{title}' created.")
    return redirect("google_integration:sheet_view", spreadsheet_id=sid)


@login_required
def sheet_view(request, spreadsheet_id: str):
    account = _require_account(request)
    if not account:
        return redirect("google_integration:connect")

    range_a1 = request.GET.get("range") or "Sheet1!A1:ZZ500"
    error = None
    meta = {}
    values: list[list[str]] = []
    styles: list[list[dict]] = []
    try:
        meta = services.get_spreadsheet_meta(account, spreadsheet_id)
        grid = services.get_grid_data(account, spreadsheet_id, range_a1)
        values = grid.get("values", [])
        styles = grid.get("styles", [])
    except Exception as exc:
        logger.exception("Failed to load spreadsheet")
        error = str(exc)

    sheet_tabs = [
        s["properties"]["title"] for s in meta.get("sheets", [])
    ]

    return render(
        request,
        "google_integration/sheet_view.html",
        {
            "account": account,
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": meta.get("spreadsheetUrl", ""),
            "title": meta.get("properties", {}).get("title", ""),
            "range_a1": range_a1,
            "sheet_tabs": sheet_tabs,
            "values": values,
            "values_json": json.dumps(values),
            "styles_json": json.dumps(styles),
            "error": error,
        },
    )


@login_required
@require_POST
def sheet_save(request, spreadsheet_id: str):
    account = _require_account(request)
    if not account:
        return JsonResponse({"ok": False, "error": "not connected"}, status=400)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    range_a1 = payload.get("range") or "Sheet1!A1:ZZ500"
    values = payload.get("values") or []
    if not isinstance(values, list):
        return JsonResponse({"ok": False, "error": "values must be a 2D list"}, status=400)

    try:
        anchor = services.range_anchor_top_left_a1(range_a1)
        result = services.update_values(account, spreadsheet_id, anchor, values)
    except Exception as exc:
        logger.exception("Failed to update values")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    return JsonResponse({"ok": True, "updatedRange": result.get("updatedRange", range_a1)})


@login_required
@require_POST
def sheet_append(request, spreadsheet_id: str):
    account = _require_account(request)
    if not account:
        return JsonResponse({"ok": False, "error": "not connected"}, status=400)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid json"}, status=400)

    range_a1 = payload.get("range") or "Sheet1!A1"
    rows = payload.get("rows") or []
    try:
        result = services.append_rows(account, spreadsheet_id, range_a1, rows)
    except Exception as exc:
        logger.exception("Failed to append rows")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    return JsonResponse({"ok": True, "updates": result.get("updates", {})})
