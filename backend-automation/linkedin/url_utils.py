from typing import Optional
from urllib.parse import quote, urlparse, unquote


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
        return raw[1:].strip() or None
    if "://" not in raw and "/" not in raw:
        return raw.lstrip("@") or None

    path = urlparse(raw).path
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return None

    reserved = {
        "p",
        "reel",
        "reels",
        "stories",
        "explore",
        "accounts",
        "direct",
        "about",
        "legal",
        "developer",
        "graphql",
        "api",
        "tags",
        "tv",
    }
    username = parts[0]
    if username.lower() in reserved:
        return None
    return unquote(username.lstrip("@")) or None


def public_id_to_url(public_id: str) -> str:
    """Convert Instagram username back to a clean profile URL."""
    if not public_id:
        return ""
    public_id = public_id.strip().lstrip("@").strip("/")
    return f"https://www.instagram.com/{quote(public_id, safe='')}/"


# Back-compat aliases used by older call sites during the Instagram cutover.
username_from_url = url_to_public_id
username_to_url = public_id_to_url
