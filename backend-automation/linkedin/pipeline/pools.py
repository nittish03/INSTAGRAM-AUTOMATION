# linkedin/pipeline/pools.py
"""Pool management via composable generators.

Three generators chain via next(upstream, None):

    find_candidate() = next(ready_source, None)
                            |
                  ready_source  <- pulls from qualify_source
                            |
                 qualify_source  <- pulls from search_source
                  (keeps searching until P > 0.5 candidates exist in exploit mode)
                            |
                  search_source  <- yields keywords (never truly exhausts)

Each run_qualification call produces at most one label, which shifts the GP
model. Rejected labels are skipped until an accepted candidate is available.
"""
from __future__ import annotations

import logging
from typing import Generator

import numpy as np

from linkedin.conf import CAMPAIGN_CONFIG
from linkedin.ml.qualifier import BayesianQualifier
from linkedin.pipeline.qualify import fetch_qualification_candidates, run_qualification
from linkedin.pipeline.search import run_search

logger = logging.getLogger(__name__)


def _needs_search(qualifier: BayesianQualifier, candidates) -> bool:

    """True only in exploit mode when no candidate meets the adaptive threshold.

    Effective threshold = max(0, base - 1/sqrt(n_obs)).
    Stays at zero until ~1/base² observations, then gradually rises
    toward base — favoring qualification over search early on.

    Returns False on cold start, explore mode, or empty candidates.
    """
    if not candidates:
        return False

    n_neg, n_pos = qualifier.class_counts
    if n_neg <= n_pos:
        # explore mode — no need to search for high-P profiles
        return False

    embeddings = np.array([c.embedding_array for c in candidates], dtype=np.float32)
    probs = qualifier.predict_probs(embeddings)
    if probs is None:
        # cold start
        return False

    # If the GP can't differentiate profiles (all predictions identical),
    # searching won't help — qualify from existing pool to build up labels.
    if len(probs) > 1 and np.ptp(probs) < 1e-6:
        logger.debug(
            "GP predictions degenerate (all ~%.3f) with %d obs — "
            "skipping search, qualifying from existing pool",
            float(probs[0]), qualifier.n_obs,
        )
        return False

    base = CAMPAIGN_CONFIG["min_positive_pool_prob"]
    n = qualifier.n_obs
    threshold = max(0.0, base - 1 / np.sqrt(n)) if n > 0 else 0.0
    if bool(np.any(probs >= threshold)):
        return False

    logger.info(
        "Pool (%d unlabeled) has no P >= %.3f in exploit mode "
        "(neg=%d, pos=%d, n_obs=%d, base=%.2f). "
        "P distribution: min=%.3f, p25=%.3f, median=%.3f, p75=%.3f, max=%.3f",
        len(candidates), threshold, n_neg, n_pos, n, base,
        float(np.min(probs)), float(np.percentile(probs, 25)),
        float(np.median(probs)), float(np.percentile(probs, 75)),
        float(np.max(probs)),
    )
    return True


def search_source(session) -> Generator[str, None, None]:
    """Yield keywords from run_search(). Stops when run_search returns None."""
    while True:
        keyword = run_search(session)
        if keyword is None:
            return
        yield keyword


def qualify_source(session, qualifier: BayesianQualifier) -> Generator[str, None, None]:
    """Yield accepted public_ids from run_qualification(), pulling from search when needed.

    In exploit mode, the effective pool is candidates with P > 0.5. When
    this pool is empty, keeps searching until high-P candidates appear or
    search is exhausted. Every yield produces a label that shifts the GP
    model. Rejected labels are recorded and skipped; the generator keeps
    qualifying until it finds an accepted lead or the pool is exhausted.
    """
    search = search_source(session)

    while True:
        candidates = fetch_qualification_candidates(session)

        # If no candidates at all, search to bring some in
        if not candidates:
            if next(search, None) is None:
                return
            candidates = fetch_qualification_candidates(session)
            if not candidates:
                return

        # In exploit mode with no P > 0.5 candidates, keep searching
        # until the positive pool is non-empty or search is exhausted.
        while _needs_search(qualifier, candidates):
            if next(search, None) is None:
                break
            candidates = fetch_qualification_candidates(session)

        result = run_qualification(session, qualifier)
        if result is None:
            continue
        yield result


def _deal_has_draft_or_outreach_task(deal, *, owner_id: int | None = None, instagram_profile_id: int | None = None) -> bool:
    """True if this deal already has a HITL draft or queued draft/send task."""
    from chat.models import ChatMessage
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Q
    from linkedin.models import Task

    lead = deal.lead
    if not lead:
        return True

    lead_ct = ContentType.objects.get_for_model(lead.__class__)
    draft_qs = ChatMessage.objects.filter(
        content_type=lead_ct,
        object_id=lead.pk,
        campaign=deal.campaign,
        is_draft=True,
        is_approved=False,
    )
    if owner_id is not None:
        draft_qs = draft_qs.filter(owner_id=owner_id)
    if instagram_profile_id is not None:
        draft_qs = draft_qs.filter(instagram_profile_id=instagram_profile_id)
    if draft_qs.exists():
        return True

    public_id = lead.public_identifier
    if not public_id:
        return True

    task_qs = Task.objects.filter(
        task_type__in=[Task.TaskType.FOLLOW_UP, Task.TaskType.SEND_MESSAGE],
        status__in=[Task.Status.PENDING, Task.Status.RUNNING],
        payload__campaign_id=deal.campaign_id,
        payload__public_id=public_id,
    )
    if owner_id is not None:
        task_qs = task_qs.filter(Q(payload__owner_id=owner_id) | Q(payload__owner_id__isnull=True))
    if instagram_profile_id is not None:
        task_qs = task_qs.filter(
            Q(payload__instagram_profile_id=instagram_profile_id)
            | Q(payload__instagram_profile_id__isnull=True)
        )
    return task_qs.exists()


def find_candidate(session, qualifier: BayesianQualifier) -> dict | None:
    """Next QUALIFIED lead needing a DM draft, backfilling via qualification if needed."""
    from crm.models import Deal
    from linkedin.enums import ProfileState
    from linkedin.url_utils import url_to_public_id

    owner_id = getattr(getattr(session, "django_user", None), "pk", None)
    if not isinstance(owner_id, int):
        owner_id = None
    instagram_profile_id = getattr(getattr(session, "instagram_profile", None), "pk", None)
    if not isinstance(instagram_profile_id, int):
        instagram_profile_id = None

    # 1. Prefer existing QUALIFIED deals that still need a draft / follow_up
    existing_qs = Deal.objects.filter(
        campaign=session.campaign,
        state=ProfileState.QUALIFIED,
    ).select_related("lead").order_by("creation_date")

    for existing in existing_qs:
        if _deal_has_draft_or_outreach_task(
            existing,
            owner_id=owner_id,
            instagram_profile_id=instagram_profile_id,
        ):
            continue
        public_id = url_to_public_id(existing.lead.instagram_url) if existing.lead else None
        if not public_id:
            continue
        return {
            "public_identifier": public_id,
            "name": f"{existing.lead.first_name} {existing.lead.last_name}",
        }

    # 2. If none, pull one from qualification pipeline
    # This will trigger search -> fetch -> run_qualification
    qualify = qualify_source(session, qualifier)
    public_id = next(qualify, None)

    if public_id:
        from crm.models import Lead
        lead = Lead.objects.get(public_identifier=public_id)
        return {
            "public_identifier": public_id,
            "name": f"{lead.first_name} {lead.last_name}",
        }

    return None

