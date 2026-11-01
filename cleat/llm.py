"""Builds the Gemini chat model shared by the support agent, the injection classifier
and the policy compiler, so the model is configured in one place.
"""

from functools import cache

from langchain_google_genai import ChatGoogleGenerativeAI

from cleat.settings import require


@cache
def get_llm() -> ChatGoogleGenerativeAI:
    """Return the shared Gemini model at temperature 0.

    Raises SettingsError naming GOOGLE_API_KEY or LLM_MODEL if either is unset.
    """
    return ChatGoogleGenerativeAI(
        model=require("LLM_MODEL"),
        google_api_key=require("GOOGLE_API_KEY"),
        temperature=0,
        # Gemini returns short-lived 503s under load; two retries ride those out.
        max_retries=2,
        timeout=45,
    )
