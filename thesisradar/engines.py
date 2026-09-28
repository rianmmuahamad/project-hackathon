"""Pluggable reasoning engines.

The product's value is the loop, the tools, the state and the interface. The
model is interchangeable, and that is not a slogan: it is enforced by this
module. Two engines implement the same small interface:

* `hermes`  — drives the locally installed Hermes agent (`hermes chat -q ... -t ''`),
              so the run shows up in Hermes' own sessions.
* `direct`  — talks to any OpenAI-compatible endpoint from the environment.

`auto` prefers Hermes and falls back to direct. If neither is available the
caller is told, rather than being handed a fabricated analysis.

No third-party imports: both engines speak HTTP with the standard library.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Sequence

from .config import REPO_ROOT as ROOT
from .jsonx import loose_objects

DEFAULT_TIMEOUT = 600


@dataclass
class Step:
    """One tool call the model asked for, and what came back."""

    name: str
    args: dict[str, Any]
    result: Any = None
    credits: int = 0

    def to_row(self, ordinal: int) -> dict[str, Any]:
        return {"ordinal": ordinal, "tool": self.name, "args": self.args,
                "credits": self.credits, "result": self.result}


@dataclass
class Turn:
    """One model reply: what it said, and what it wanted to run."""

    text: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class EngineUnavailable(RuntimeError):
    pass


class Engine:
    """Interface every engine implements."""

    name = "engine"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def identify(self) -> dict[str, Any]:
        return {"engine": self.name, "model": getattr(self, "model", None)}

    def reply(self, system: str, messages: list[dict[str, Any]],
              tools: Sequence[dict[str, Any]]) -> Turn:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Hermes
# --------------------------------------------------------------------------
class HermesEngine(Engine):
    """Drives Hermes headless. Tools are passed as a prompt-level catalogue.

    `-t ''` disables Hermes' own toolsets: the agent under evaluation must not be
    able to reach the network or the filesystem except through our tools, or the
    transcript would stop being evidence.
    """

    name = "hermes"

    # Hermes' internal turn budget, not ours. Our loop decides how many rounds the
    # investigation gets; this only needs to be large enough that the model can
    # think and then emit its TOOL CALLS block. At 4 it sometimes spent every turn
    # reasoning and hit the recovery path instead of answering.
    max_turns = "8"

    def __init__(self, binary: str | None = None, model: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT) -> None:
        self.binary = binary or shutil.which("hermes") or ""
        self.model = model
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        if not self.binary:
            return False, "hermes executable not found on PATH"
        return True, self.binary

    def reply(self, system: str, messages: list[dict[str, Any]],
              tools: Sequence[dict[str, Any]]) -> Turn:
        prompt = (system + "\n\n"
                  + "\n\n".join(_render(m) for m in messages if m.get("role") != "system"))
        # The prompt travels as argv rather than a temp file: one fewer artifact,
        # one fewer permission failure, and `hermes chat -q` takes it directly.
        cmd = [self.binary, "chat", "-q", prompt, "-Q", "-t", "",
               "--max-turns", self.max_turns, "--ignore-rules"]
        if self.model:
            cmd += ["-m", self.model]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout,
                                  check=False, cwd=str(ROOT))
        except subprocess.TimeoutExpired as err:
            raise EngineUnavailable(f"hermes timed out after {self.timeout}s") from err
        if proc.returncode != 0:
            raise EngineUnavailable(
                f"hermes exited {proc.returncode}: {(proc.stderr or proc.stdout or '')[-400:]}"
            )
        return parse_text_turn(clean_stdout(proc.stdout or ""))


def _render(message: dict[str, Any]) -> str:
    """One transcript message as prompt text, tools included."""
    role = message.get("role")
    if role == "assistant":
        return f"[your previous reply]\n{message.get('content') or ''}"
    if role == "tool":
        return "[tool result]\n" + str(message.get("content") or "")
    return f"[{role}]\n{message.get('content') or ''}"


def clean_stdout(text: str) -> str:
    """Drop the CLI's own footer lines so only the model's answer remains."""
    keep = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("session_id:"):
            continue
        keep.append(line)
    return "\n".join(keep).strip()


def parse_text_turn(text: str) -> Turn:
    """Read a prompt-level reply: prose, then an optional fenced JSON block.

    Kept deliberately literal — if the block is absent or malformed this returns
    no calls, and the loop asks again instead of guessing what was meant.
    """
    calls: list[dict[str, Any]] = []
    body = text
    marker = "TOOL CALLS:"
    if marker in text:
        # The model narrates, then emits the marker. Everything before it is its
        # reasoning (kept as the reply's text); everything after is the call.
        # Cutting at the *last* marker avoids leaving stray braces in the prose.
        head, _, tail = text.rpartition(marker)
        body = head.rstrip()
        block = tail.strip()
        if "```" in block:
            parts = block.split("```")
            if len(parts) >= 2:
                block = parts[1]
                if block.lstrip().lower().startswith("json"):
                    block = block.lstrip()[4:]
        try:
            parsed = json.loads(block.strip())
            if isinstance(parsed, dict):
                parsed = [parsed]
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("tool"):
                        calls.append({"name": item["tool"],
                                      "arguments": item.get("args") or item.get("arguments") or {}})
        except ValueError:
            calls = []
    if not calls:
        for item in loose_objects(text):
            if isinstance(item, dict) and item.get("tool"):
                calls.append({"name": item["tool"],
                              "arguments": item.get("args") or item.get("arguments") or {}})
    return Turn(text=body.strip(), calls=calls, raw={"stdout": text})


# --------------------------------------------------------------------------
# Direct OpenAI-compatible
# --------------------------------------------------------------------------
class DirectEngine(Engine):
    """Any OpenAI-compatible chat-completions endpoint, with real tool calling.

    Used as the fallback engine *and* as the proof that Hermes is not
    load-bearing: the same loop, tools and state, a different model server.
    """

    name = "direct"

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        self.model = model or os.environ.get("THESISRADAR_MODEL") or "gpt-4o-mini"
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no OPENAI_API_KEY in the environment"
        return True, f"{self.base_url} ({self.model})"

    def reply(self, system: str, messages: list[dict[str, Any]],
              tools: Sequence[dict[str, Any]]) -> Turn:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "temperature": 0.2,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
            body["tool_choice"] = "auto"

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "thesisradar/0.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:400]
            raise EngineUnavailable(f"{err.code} from {self.base_url}: {detail}") from err
        except (urllib.error.URLError, ValueError) as err:
            raise EngineUnavailable(f"model endpoint failed: {err}") from err

        message = ((payload.get("choices") or [{}])[0].get("message") or {})
        calls: list[dict[str, Any]] = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            args: Any = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    args = {}
            calls.append({"name": fn.get("name"), "arguments": args, "id": call.get("id")})
        return Turn(text=message.get("content") or "", calls=calls, raw=payload)


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------
def make(choice: str = "auto", model: str | None = None) -> tuple[Engine, str]:
    """Pick an engine. Returns (engine, note) so the caller can say why."""
    choice = (choice or "auto").lower()
    hermes = HermesEngine(model=model)
    direct = DirectEngine(model=model)

    if choice == "hermes":
        ok, detail = hermes.available()
        if not ok:
            raise EngineUnavailable(f"engine=hermes requested but unavailable: {detail}")
        return hermes, detail
    if choice == "direct":
        ok, detail = direct.available()
        if not ok:
            raise EngineUnavailable(f"engine=direct requested but unavailable: {detail}")
        return direct, detail

    ok, detail = hermes.available()
    if ok:
        return hermes, detail
    ok2, detail2 = direct.available()
    if ok2:
        return direct, f"hermes unavailable ({detail}); using direct: {detail2}"
    raise EngineUnavailable(
        f"no reasoning engine available — hermes: {detail}; direct: {detail2}"
    )


def describe() -> dict[str, Any]:
    """What is available right now, for `thesisradar doctor`."""
    hermes = HermesEngine()
    direct = DirectEngine()
    h_ok, h_detail = hermes.available()
    d_ok, d_detail = direct.available()
    return {
        "hermes": {"available": h_ok, "detail": h_detail},
        "direct": {"available": d_ok, "detail": d_detail,
                   "model": direct.model, "base_url": direct.base_url},
    }