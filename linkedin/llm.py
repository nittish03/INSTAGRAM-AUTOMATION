"""LLM provider helpers (OpenAI-compatible, Azure, Gemini)."""
from __future__ import annotations

from urllib.parse import urlparse

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import AzureChatOpenAI, ChatOpenAI


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


def build_chat_llm(site_config, *, temperature: float, timeout: int = 60):
    """Return a LangChain chat model from SiteConfig fields."""
    provider = (site_config.llm_provider or "").strip().lower() or "openai"
    api_key = (site_config.llm_api_key or "").strip()
    model = (site_config.ai_model or "").strip()
    base_url = (site_config.llm_api_base or "").strip() or None
    allow_custom_temperature = not _is_fixed_temperature_model(model)

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in Site Configuration.")
    if not model and provider != "azure":
        raise ValueError("AI model is not set in Site Configuration.")

    if provider == "gemini":
        kwargs = {
            "model": model,
            "google_api_key": api_key,
            "timeout": timeout,
        }
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
        if allow_custom_temperature:
            kwargs["temperature"] = temperature
        return AzureChatOpenAI(**kwargs)

    kwargs = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "timeout": timeout,
    }
    if allow_custom_temperature:
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


def test_llm_connection(site_config) -> tuple[bool, str]:
    """Run a minimal live LLM call and return (ok, message)."""
    try:
        llm = build_chat_llm(site_config, temperature=0.0, timeout=30)
        response = llm.invoke("Reply with exactly: OK")
        text = getattr(response, "content", "")
        return True, f"Connected. Sample response: {text!r}"
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"
