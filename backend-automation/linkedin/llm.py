"""LLM provider helpers (OpenAI-compatible, Azure, Gemini)."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import AzureChatOpenAI, ChatOpenAI

_SUPPORTED_PROVIDERS = {"openai", "azure", "gemini"}
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
_HTTP_TIMEOUT = 20


def _normalize_azure_endpoint(raw_endpoint: str) -> str:
    """Accept Azure root URL or full API URL and return root endpoint."""
    value = (raw_endpoint or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return value


def _is_fixed_temperature_model(name: str) -> bool:
    """Return True for model families that only allow default temperature."""
    normalized = (name or "").strip().lower()
    return normalized.startswith("gpt-5")


def validate_llm_site_config(site_config) -> tuple[bool, str]:
    """Validate SiteConfig fields required to construct an LLM client."""
    provider = (site_config.llm_provider or "").strip().lower()
    api_key = (site_config.llm_api_key or "").strip()
    model = (site_config.ai_model or "").strip()
    base_url = (site_config.llm_api_base or "").strip()
    azure_deployment = (site_config.azure_deployment or "").strip()

    if not provider:
        return False, "LLM provider is not set in Site Configuration."
    if provider not in _SUPPORTED_PROVIDERS:
        return False, f"Unsupported LLM provider: {provider!r}."
    if not api_key:
        return False, "LLM API key is not set in Site Configuration."

    if provider == "azure":
        if not azure_deployment and not model:
            return False, "Azure deployment (or model fallback) is not set in Site Configuration."
        if not _normalize_azure_endpoint(base_url):
            return False, "Azure endpoint (LLM API Base URL) is not set in Site Configuration."
        return True, "ok"

    if not model:
        return False, "AI model is not set in Site Configuration."
    return True, "ok"


def build_chat_llm(
    site_config,
    *,
    temperature: float,
    timeout: int = 60,
    max_retries: int | None = None,
):
    """Return a LangChain chat model from SiteConfig fields."""
    provider = (site_config.llm_provider or "").strip().lower()
    api_key = (site_config.llm_api_key or "").strip()
    model = (site_config.ai_model or "").strip()
    base_url = (site_config.llm_api_base or "").strip() or None
    allow_custom_temperature = not _is_fixed_temperature_model(model)

    ok, reason = validate_llm_site_config(site_config)
    if not ok:
        raise ValueError(reason)

    if provider == "gemini":
        kwargs = {
            "model": model,
            "google_api_key": api_key,
            "timeout": timeout,
        }
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if allow_custom_temperature:
            kwargs["temperature"] = temperature
        return ChatGoogleGenerativeAI(**kwargs)

    if provider == "azure":
        azure_deployment = (site_config.azure_deployment or model).strip()
        if not azure_deployment:
            raise ValueError("Azure deployment is not set in Site Configuration.")
        if _is_fixed_temperature_model(azure_deployment):
            allow_custom_temperature = False
        azure_endpoint = _normalize_azure_endpoint(base_url or "")
        if not azure_endpoint:
            raise ValueError("Azure endpoint (LLM API Base URL) is not set in Site Configuration.")

        kwargs = {
            "azure_deployment": azure_deployment,
            "azure_endpoint": azure_endpoint,
            "api_key": api_key,
            "api_version": (site_config.azure_api_version or "2024-10-21").strip(),
            "timeout": timeout,
        }
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if allow_custom_temperature:
            kwargs["temperature"] = temperature
        return AzureChatOpenAI(**kwargs)

    kwargs = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "timeout": timeout,
    }
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    if allow_custom_temperature:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


def format_llm_error(exc: Exception) -> str:
    """Return a concise, user-facing LLM error message."""
    text = str(exc)
    upper = text.upper()
    if "429" in text or "RESOURCE_EXHAUSTED" in upper or "RATE LIMIT" in upper:
        model_hint = ""
        if "gemini-2.5-pro" in text.lower():
            model_hint = " Try gemini-2.5-flash (free tier) or enable billing for Pro."
        return (
            "Gemini quota exceeded (429). Your API key has no remaining quota for this model."
            + model_hint
        )
    if "404" in text or "NOT FOUND" in upper:
        return "Model or endpoint not found (404). Check provider, model name, and API base URL."
    if len(text) > 280:
        return f"{exc.__class__.__name__}: {text[:280]}…"
    return f"{exc.__class__.__name__}: {text}"


def extract_llm_reply(response) -> str:
    text = getattr(response, "content", "")
    if isinstance(text, list):
        parts = []
        for block in text:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        text = "".join(parts)
    reply = str(text or "").strip()
    return reply or "(empty response)"


def _http_get_json(url: str, headers: dict | None = None) -> dict:
    req = Request(url, headers=headers or {}, method="GET")
    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            message = payload.get("error", {}).get("message") or body
        except json.JSONDecodeError:
            message = body or exc.reason
        raise ValueError(f"HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise ValueError(f"Network error: {exc.reason}") from exc


def _gemini_model_id(raw_name: str) -> str:
    name = (raw_name or "").strip()
    if name.startswith("models/"):
        return name.split("/", 1)[1]
    return name


def _list_gemini_models(api_key: str) -> tuple[list[dict], int]:
    query = urlencode({"key": api_key, "pageSize": 200})
    payload = _http_get_json(
        f"https://generativelanguage.googleapis.com/v1beta/models?{query}",
    )
    rows = payload.get("models") or []
    models: list[dict] = []
    filtered_out = 0
    for row in rows:
        methods = row.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            filtered_out += 1
            continue
        model_id = _gemini_model_id(str(row.get("name") or ""))
        if not model_id:
            filtered_out += 1
            continue
        display = str(row.get("displayName") or model_id).strip()
        label = f"{model_id} ({display})" if display and display != model_id else model_id
        models.append({"id": model_id, "label": label})
    models.sort(key=lambda item: (_gemini_model_sort_key(item["id"]), item["id"]))
    return models, filtered_out


def _gemini_model_sort_key(model_id: str) -> tuple[int, str]:
    lowered = model_id.lower()
    if lowered == _GEMINI_DEFAULT_MODEL:
        return (0, model_id)
    if lowered.startswith("gemini-2.5"):
        return (1, model_id)
    if lowered.startswith("gemini-"):
        return (2, model_id)
    return (3, model_id)


def _list_openai_models(api_key: str, base_url: str | None) -> tuple[list[dict], int]:
    root = (base_url or "https://api.openai.com/v1").rstrip("/")
    payload = _http_get_json(
        f"{root}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    rows = payload.get("data") or []
    models: list[dict] = []
    filtered_out = 0
    for row in rows:
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            filtered_out += 1
            continue
        lowered = model_id.lower()
        if not (
            lowered.startswith("gpt-")
            or lowered.startswith("o1")
            or lowered.startswith("o3")
            or lowered.startswith("o4")
            or "chat" in lowered
        ):
            filtered_out += 1
            continue
        models.append({"id": model_id, "label": model_id})
    models.sort(key=lambda item: item["id"], reverse=True)
    return models, filtered_out


def _list_azure_deployments(site_config) -> tuple[list[dict], int]:
    api_key = (site_config.llm_api_key or "").strip()
    endpoint = _normalize_azure_endpoint(site_config.llm_api_base or "")
    if not endpoint:
        raise ValueError("Azure endpoint (LLM API Base URL) is not set.")
    api_version = (site_config.azure_api_version or "2024-10-21").strip()
    query = urlencode({"api-version": api_version})
    payload = _http_get_json(
        f"{endpoint.rstrip('/')}/openai/deployments?{query}",
        headers={"api-key": api_key},
    )
    rows = payload.get("data") or []
    models: list[dict] = []
    filtered_out = 0
    for row in rows:
        deployment = str(row.get("id") or row.get("name") or "").strip()
        if not deployment:
            filtered_out += 1
            continue
        model_name = str(row.get("model") or deployment).strip()
        label = f"{deployment} ({model_name})" if model_name != deployment else deployment
        models.append({"id": deployment, "label": label})
    models.sort(key=lambda item: item["id"])
    return models, filtered_out


def list_llm_models(site_config) -> dict:
    """Fetch provider models/deployments for the site-config picker."""
    provider = (site_config.llm_provider or "").strip().lower()
    api_key = (site_config.llm_api_key or "").strip()

    ok, reason = validate_llm_site_config(site_config)
    if not ok:
        raise ValueError(reason)

    if provider == "gemini":
        models, filtered_out = _list_gemini_models(api_key)
        return {
            "models": models,
            "source": "gemini",
            "filteredOut": filtered_out,
            "hint": f"Filtered Gemini choices. Blank uses {_GEMINI_DEFAULT_MODEL}.",
        }

    if provider == "azure":
        models, filtered_out = _list_azure_deployments(site_config)
        return {
            "models": models,
            "source": "azure",
            "filteredOut": filtered_out,
            "hint": "Azure deployment names — pick one to use as the model/deployment.",
        }

    base_url = (site_config.llm_api_base or "").strip() or None
    models, filtered_out = _list_openai_models(api_key, base_url)
    return {
        "models": models,
        "source": "openai",
        "filteredOut": filtered_out,
        "hint": "Filtered chat-capable OpenAI models.",
    }


def test_llm_connection(site_config) -> tuple[bool, str]:
    """Run a minimal live LLM call and return (ok, message)."""
    try:
        llm = build_chat_llm(site_config, temperature=0.0, timeout=20, max_retries=0)
        response = llm.invoke("Reply with exactly: OK")
        text = extract_llm_reply(response)
        return True, f"Connected. Sample response: {text!r}"
    except Exception as exc:
        return False, format_llm_error(exc)
