from typing import Optional
from urllib.parse import quote, urlparse, unquote

# Instagram chrome / footer / system paths that look like profile URLs.
RESERVED_USERNAMES = frozenset(
    {
        "p",
        "reel",
        "reels",
        "stories",
        "explore",
        "accounts",
        "direct",
        "about",
        "about-us",
        "legal",
        "developer",
        "graphql",
        "api",
        "tags",
        "tv",
        "blog",
        "web",
        "popular",
        "directory",
        "help",
        "privacy",
        "safety",
        "terms",
        "lite",
        "nametag",
        "session",
        "challenge",
        "inbox",
        "notifications",
        "oauth",
        "static",
        "support",
        "press",
        "jobs",
        "meta",
        "facebook",
        "instagram",
    }
)

# Single-token handles that almost never represent a real business prospect.
GENERIC_JUNK_USERNAMES = frozenset(
    {
        "agency",
        "agencies",
        "brand",
        "brands",
        "business",
        "coach",
        "coaching",
        "creative",
        "design",
        "designer",
        "digital",
        "ecommerce",
        "founder",
        "freelance",
        "freelancer",
        "home",
        "info",
        "marketing",
        "media",
        "official",
        "online",
        "page",
        "shop",
        "startup",
        "studio",
        "team",
        "user",
        "website",
        "www",
    }
)


def is_plausible_instagram_username(username: str | None) -> bool:
    """True when a handle looks like a real account, not chrome/junk."""
    if not username:
        return False
    cleaned = username.strip().lstrip("@").strip("/")
    if not cleaned:
        return False
    lower = cleaned.lower()
    if lower in RESERVED_USERNAMES or lower in GENERIC_JUNK_USERNAMES:
        return False
    if lower.replace("-", "").replace("_", "").replace(".", "") in {
        "aboutus",
        "contactus",
        "privacypolicy",
        "termsofservice",
    }:
        return False
    # Instagram usernames: 1–30 chars, letters/digits/._ — reject ultra-short generics.
    if len(cleaned) < 3:
        return False
    if len(cleaned) > 30:
        return False
    if not all(ch.isalnum() or ch in "._" for ch in cleaned):
        # Allow hyphen only if rare real handles use it; IG officially disallows '-', drop them.
        if "-" in cleaned:
            return False
        return False
    # Reject pure generic words that slipped past the set (single alphabetic token <= 4).
    if cleaned.isalpha() and len(cleaned) <= 3:
        return False
    return True


def url_to_public_id(url: str) -> Optional[str]:
    """
    Extract an Instagram username from a profile URL.

    Accepts:
    - https://www.instagram.com/username/
    - https://instagram.com/username
    - Bare usernames (returned as-is when no scheme/path)

    Returns None for empty values or non-profile paths (e.g. /p/, /reel/, /explore/).
    """
    if not url:
        return None

    raw = url.strip()
    if not raw:
        return None

    # Bare username (no URL)
    if "://" not in raw and "/" not in raw and raw.startswith("@"):
        pid = raw[1:].strip() or None
        return pid if is_plausible_instagram_username(pid) else None
    if "://" not in raw and "/" not in raw:
        pid = raw.lstrip("@") or None
        return pid if is_plausible_instagram_username(pid) else None

    path = urlparse(raw).path
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return None

    username = unquote(parts[0].lstrip("@")) or None
    if not username or username.lower() in RESERVED_USERNAMES:
        return None
    if not is_plausible_instagram_username(username):
        return None
    return username


def public_id_to_url(public_id: str) -> str:
    """Convert Instagram username back to a clean profile URL."""
    if not public_id:
        return ""
    public_id = public_id.strip().lstrip("@").strip("/")
    return f"https://www.instagram.com/{quote(public_id, safe='')}/"


# Back-compat aliases used by older call sites during the Instagram cutover.
username_from_url = url_to_public_id
username_to_url = public_id_to_url
