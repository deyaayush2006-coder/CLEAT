"""Builds the Gemini chat model shared by the support agent, the injection classifier
and the policy compiler, so the model is configured in one place.

Gemini's free tier answers bursts with 429 errors that say how long to wait. Google's SDK
ignores that delay and retries on its own short backoff, which only burns more quota, so
SDK retries are off and every call goes through `with_retries` instead.
"""

import contextvars
import math
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cache
from typing import Any

from langchain_core.exceptions import ModelAPIError, ModelRateLimitError
from langchain_google_genai import ChatGoogleGenerativeAI

from cleat.settings import require

BUSY_MESSAGE = "The AI is busy, retrying…"
# Used when a 429 carries no retry delay: 20 s, then 40 s, then 40 s again.
RATE_LIMIT_FALLBACK_DELAYS = (20.0, 40.0, 40.0)
# A suggested delay longer than this means a quota that will not reset during a demo
# (for example the daily one), so waiting would only leave the visitor staring at a spinner.
MAX_RATE_LIMIT_DELAY = 60.0
# Replaces the SDK's own short retries for transient server errors (5xx).
SERVER_ERROR_DELAYS = (2.0, 4.0)

# The page that started a call sets this to show "The AI is busy, retrying…" while it waits.
_on_retry: contextvars.ContextVar[Callable[[int, float], None] | None] = contextvars.ContextVar(
    "on_retry", default=None
)
_RETRY_IN = re.compile(r"retry in\s*(\d+(?:\.\d+)?)\s*s", re.I)
_RETRY_DELAY = re.compile(r"retry_?delay\W+(?:seconds\W+)?(\d+(?:\.\d+)?)", re.I)


@contextmanager
def on_retry(callback: Callable[[int, float], None]) -> Iterator[None]:
    """Call `callback(attempt, delay_seconds)` before each retry made inside this block."""
    token = _on_retry.set(callback)
    try:
        yield
    finally:
        _on_retry.reset(token)


def is_rate_limit(error: BaseException) -> bool:
    """True for Gemini's 429 / RESOURCE_EXHAUSTED errors."""
    text = str(error)
    return isinstance(error, ModelRateLimitError) or "429" in text or "RESOURCE_EXHAUSTED" in text


def suggested_delay(error: BaseException) -> float | None:
    """Return the retry delay Gemini put in a 429 error, in seconds, or None if it gave none."""
    text = str(error)
    for pattern in (_RETRY_IN, _RETRY_DELAY):
        if match := pattern.search(text):
            return float(match.group(1))
    return None


def with_retries(call: Callable[[], Any], sleep: Callable[[float], None] = time.sleep) -> Any:
    """Run `call`, retrying Gemini rate limits up to 3 times and server errors up to 2 times.

    A rate limit waits for the delay Gemini suggests (or 20 s, then 40 s). If Gemini asks
    for more than MAX_RATE_LIMIT_DELAY, or retries run out, the last error is raised.
    """
    attempt = 0
    while True:
        try:
            return call()
        except Exception as error:
            if is_rate_limit(error):
                if attempt >= len(RATE_LIMIT_FALLBACK_DELAYS):
                    raise
                suggested = suggested_delay(error)
                if suggested is None:
                    delay = RATE_LIMIT_FALLBACK_DELAYS[attempt]
                elif suggested > MAX_RATE_LIMIT_DELAY:
                    raise
                else:
                    delay = math.ceil(suggested) + 1  # a little margin past the quota window
            elif isinstance(error, ModelAPIError) and attempt < len(SERVER_ERROR_DELAYS):
                delay = SERVER_ERROR_DELAYS[attempt]
            else:
                raise
            attempt += 1
            if (notify := _on_retry.get()) is not None:
                notify(attempt, delay)
            sleep(delay)


class _Retrying:
    """Wraps a model or runnable so that `invoke` retries, and so do the runnables it creates."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return with_retries(lambda: self._inner.invoke(*args, **kwargs))

    def bind_tools(self, *args: Any, **kwargs: Any) -> "_Retrying":
        return _Retrying(self._inner.bind_tools(*args, **kwargs))

    def with_structured_output(self, *args: Any, **kwargs: Any) -> "_Retrying":
        return _Retrying(self._inner.with_structured_output(*args, **kwargs))


@cache
def get_llm() -> _Retrying:
    """Return the shared Gemini model at temperature 0, with Cleat's retry handling.

    Raises SettingsError naming GOOGLE_API_KEY or LLM_MODEL if either is unset.
    """
    return _Retrying(
        ChatGoogleGenerativeAI(
            model=require("LLM_MODEL"),
            google_api_key=require("GOOGLE_API_KEY"),
            temperature=0,
            # 1 means a single attempt: the SDK reads 0 as "use its default of 5 retries".
            max_retries=1,
            timeout=45,
        )
    )
