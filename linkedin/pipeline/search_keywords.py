# linkedin/ml/search_keywords.py
"""LLM-based generation of LinkedIn People search keywords."""
from __future__ import annotations

import logging

import jinja2
from pydantic import BaseModel, Field

from linkedin.conf import PROMPTS_DIR

logger = logging.getLogger(__name__)


class SearchKeywords(BaseModel):
    """Structured LLM output for search keyword generation."""
    keywords: list[str] = Field(description="List of LinkedIn People search queries")


def generate_search_keywords(
    product_docs: str,
    campaign_objective: str,
    n_keywords: int = 10,
    exclude_keywords: list[str] | None = None,
) -> list[str]:
    """Call LLM to generate LinkedIn search keywords from campaign context.

    Returns a list of search query strings.
    """
    from linkedin.conf import get_llm_site_config
    from linkedin.llm import build_chat_llm

    site_config = get_llm_site_config()

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(PROMPTS_DIR)))
    template = env.get_template("search_keywords.j2")

    prompt = template.render(
        product_docs=product_docs,
        campaign_objective=campaign_objective,
        n_keywords=n_keywords,
        exclude_keywords=exclude_keywords or [],
    )

    llm = build_chat_llm(site_config, temperature=0.9, timeout=60)
    structured_llm = llm.with_structured_output(SearchKeywords)
    result = structured_llm.invoke(prompt)
    if result is None:
        raise RuntimeError("LLM returned unparseable keyword response.")

    logger.info("Generated %d search keywords via LLM", len(result.keywords))
    return result.keywords
