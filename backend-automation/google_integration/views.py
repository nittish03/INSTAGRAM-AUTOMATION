"""Google integration legacy views.

All Google flows are now JSON APIs in ``linkedin.views``
(``/api/google/...``) consumed by the Next.js frontend. This module is kept
empty so existing imports of ``google_integration.views`` won't break, but
no view is registered in URLConf any more.
"""
from __future__ import annotations
