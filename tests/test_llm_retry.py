"""Tests for Cleat's Gemini retry handling in cleat.llm, with a fake clock and fake errors."""

from typing import Any

import pytest
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError

from cleat import llm


class Flaky:
    """Raises the queued errors in order, then returns "ok"."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def rate_limit(text: str = "") -> ModelRateLimitError:
    return ModelRateLimitError(f"Error calling model 'gemini' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {text}")


@pytest.fixture
def slept() -> list[float]:
    return []


def run(call: Flaky, slept: list[float]) -> Any:
    return llm.with_retries(call, sleep=slept.append)


def test_gemini_s_suggested_delay_is_waited_for(slept: list[float]) -> None:
    call = Flaky(rate_limit("Please retry in 17.3s."), rate_limit("'retryDelay': '9s'"))
    assert run(call, slept) == "ok"
    assert slept == [19, 10]  # rounded up, plus a second of margin
    assert call.calls == 3


def test_without_a_suggested_delay_it_waits_20_then_40_seconds(slept: list[float]) -> None:
    assert run(Flaky(rate_limit(), rate_limit()), slept) == "ok"
    assert slept == [20, 40]


def test_after_three_retries_the_rate_limit_error_is_raised(slept: list[float]) -> None:
    call = Flaky(*(rate_limit() for _ in range(4)))
    with pytest.raises(ModelRateLimitError):
        run(call, slept)
    assert call.calls == 4 and len(slept) == 3


def test_a_delay_too_long_for_a_demo_is_not_waited_for(slept: list[float]) -> None:
    with pytest.raises(ModelRateLimitError):
        run(Flaky(rate_limit("Please retry in 3600s.")), slept)
    assert slept == []


def test_server_errors_are_retried_twice_quickly(slept: list[float]) -> None:
    assert run(Flaky(ModelAPIError("503 UNAVAILABLE"), ModelAPIError("503 UNAVAILABLE")), slept) == "ok"
    assert slept == [2.0, 4.0]
    with pytest.raises(ModelAPIError):
        run(Flaky(*(ModelAPIError("503") for _ in range(3))), [])


def test_other_errors_are_not_retried(slept: list[float]) -> None:
    call = Flaky(ValueError("bad request"))
    with pytest.raises(ValueError):
        run(call, slept)
    assert call.calls == 1 and slept == []


def test_the_page_is_told_before_each_retry(slept: list[float]) -> None:
    notices: list[tuple[int, float]] = []
    with llm.on_retry(lambda attempt, delay: notices.append((attempt, delay))):
        run(Flaky(rate_limit(), rate_limit()), slept)
    assert notices == [(1, 20), (2, 40)]
    run(Flaky(rate_limit()), slept)  # outside the block nobody is notified
    assert len(notices) == 2


def test_runnables_made_from_the_model_also_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)

    class FakeModel:
        def __init__(self) -> None:
            self.flaky = Flaky(rate_limit())

        def invoke(self, messages: Any) -> str:
            return self.flaky()

        def bind_tools(self, tools: Any) -> "FakeModel":
            return self

        def with_structured_output(self, schema: Any) -> "FakeModel":
            return self

    wrapped = llm._Retrying(FakeModel())
    assert wrapped.bind_tools([]).invoke([]) == "ok"
    assert llm._Retrying(FakeModel()).with_structured_output(dict).invoke([]) == "ok"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("Please retry in 17.3s.", 17.3), ("'retryDelay': '9s'", 9.0), ("[retry_delay { seconds: 31 }]", 31.0), ("no hint", None)],
)
def test_every_retry_delay_format_gemini_uses_is_read(text: str, seconds: float | None) -> None:
    assert llm.suggested_delay(rate_limit(text)) == seconds
