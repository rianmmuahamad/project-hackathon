"""Jev (TypeSafe System One) — the decision layer.

The product has three jobs, and they belong to three different things:

* **code** measures reported numbers (see `audit.measure`);
* **Jev** decides what those numbers mean for a written claim, and guards the
  prose that gets written about it;
* **the LLM** supplies the one thing neither can: open-ended context prose.

Jev is not an LLM. It generates no text; it evaluates typed questions against a
state and returns typed answers with a probability distribution and a confidence.
That is why it is used for the decision and for the guardrail — a verdict a
program branches on should not be parsed out of prose, and "did the model invent
a number?" is a yes/no question with a calibrated answer, not a sentence.

Standard library only, matching `sectors.py`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import settings

USER_AGENT = "thesisradar/0.1 (+https://github.com/rianmmuahamad/project-hackathon)"


class JevUnavailable(RuntimeError):
    """The decision layer could not answer.

    Always caught by the caller, never fatal: the product must keep working with
    the agent deciding alone rather than refusing to produce a verdict.
    """


@dataclass
class JevAnswer:
    name: str
    kind: str                        # "choice" | "score" | "noul"
    value: str | float               # choice label | score level | noul probability
    confidence: float | None = None  # absent for noul
    probabilities: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        """Flat shape for the transcript and the evidence table."""
        return {
            "question": self.name,
            "type": self.kind,
            "answer": self.value,
            "confidence": None if self.confidence is None
            else round(float(self.confidence), 3),
            "probabilities": {k: round(float(v), 3)
                              for k, v in (self.probabilities or {}).items()},
        }


@dataclass
class JevDecision:
    answers: dict[str, JevAnswer]
    usage: dict[str, Any]
    seconds: float
    model: str

    def rows(self) -> list[dict[str, Any]]:
        return [answer.as_row() for answer in self.answers.values()]


class JevClient:
    """One transport path to the gateway. Nothing else in the product calls it."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int | None = None) -> None:
        cfg = settings()
        self.base_url = (base_url or cfg.jev_base).rstrip("/")
        self.api_key = api_key if api_key is not None else cfg.jev_key
        self.model = model or cfg.jev_model
        self.timeout = timeout or cfg.jev_timeout

    # -- availability ------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        """Whether a request is worth attempting, and why not when it is not."""
        if not self.api_key:
            return False, "no THESISRADAR_JEV_KEY in the environment"
        return True, f"{self.base_url} ({self.model})"

    # -- transport ---------------------------------------------------------
    def raw_ask(self, state: str, questions: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], float]:
        """POST one state with all its questions. Returns (payload, seconds)."""
        if not self.api_key:
            raise JevUnavailable("no THESISRADAR_JEV_KEY in the environment")

        # No `system_prompt` field: this gateway rejects it with a 400
        # ("Invalid request"), verified by isolating it against the same body
        # without it. Direction therefore has to live in the question wording —
        # which is where it is most effective anyway, since each question is
        # evaluated independently and the state stays the evidence and nothing else.
        body = json.dumps({
            "state": state,
            "model": self.model,
            "questions": questions,
        }).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/systemone",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            # The gateway answers some failures with an HTML body, so the status
            # code alone is not enough to report.
            detail = err.read().decode("utf-8", "replace")[:400]
            raise JevUnavailable(f"{err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise JevUnavailable(f"network error: {err.reason}") from err
        except TimeoutError as err:
            raise JevUnavailable(f"timed out after {self.timeout}s") from err

        elapsed = time.monotonic() - started
        try:
            payload = json.loads(text)
        except ValueError as err:
            raise JevUnavailable(f"gateway returned non-JSON: {text[:200]}") from err
        if not isinstance(payload, dict):
            raise JevUnavailable(f"gateway returned {type(payload).__name__}, not an object")
        return payload, elapsed

    # -- normalisation -----------------------------------------------------
    def ask(self, state: str, questions: dict[str, dict[str, Any]]) -> JevDecision:
        """Ask typed questions and return validated answers.

        The gateway proxies an upstream model, so every field is coerced and
        checked here. A malformed answer raises rather than yielding NaN that
        would silently poison a confidence downstream.
        """
        payload, elapsed = self.raw_ask(state, questions)
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict):
            raise JevUnavailable(f"response has no answers object: {str(payload)[:200]}")

        answers: dict[str, JevAnswer] = {}
        for name, item in raw_answers.items():
            if not isinstance(item, dict):
                raise JevUnavailable(f"answer '{name}' was malformed: {item!r}")
            kind = str(item.get("type") or "")
            if kind == "choice":
                if item.get("choice") is None:
                    raise JevUnavailable(f"answer '{name}' was malformed: {item}")
                value: str | float = str(item["choice"])
            elif kind == "score":
                value = _number(item.get("score"), name, item)
            elif kind == "noul":
                value = min(1.0, max(0.0, _number(item.get("noul"), name, item)))
            else:
                raise JevUnavailable(f"answer '{name}' has unknown type {kind!r}")

            confidence: float | None = None
            if kind in ("choice", "score") and item.get("confidence") is not None:
                confidence = min(1.0, max(0.0, _number(item.get("confidence"), name, item)))

            probabilities: dict[str, float] = {}
            for key, prob in (item.get("probabilities") or {}).items():
                probabilities[str(key)] = float(prob)

            answers[str(name)] = JevAnswer(name=str(name), kind=kind, value=value,
                                          confidence=confidence,
                                          probabilities=probabilities, raw=item)

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return JevDecision(answers=answers, usage=usage, seconds=elapsed,
                           model=str(payload.get("model") or self.model))


def _number(value: Any, name: str, item: dict[str, Any]) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as err:
        raise JevUnavailable(f"answer '{name}' was malformed: {item}") from err
    if out != out:  # NaN
        raise JevUnavailable(f"answer '{name}' was malformed: {item}")
    return out


def jev_from_settings() -> JevClient | None:
    """A client when the decision layer is configured, else None."""
    return JevClient() if settings().jev_configured else None


def describe() -> dict[str, Any]:
    """Availability for `doctor` and `/api/health`, with no network call."""
    client = JevClient()
    available, detail = client.available()
    return {"available": available, "detail": detail, "model": client.model,
            "base_url": client.base_url}
