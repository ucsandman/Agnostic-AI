"""
agent/llm/client.py — Universal LLM Client Adapter
Supports LM Studio (localhost:1234), Ollama (localhost:11434), OpenAI, vLLM, DeepSeek, Claude, and Gemini endpoints.
"""

import os
import re
import json
import time
import uuid
import subprocess
import threading
import shutil
from functools import lru_cache
from types import SimpleNamespace
from typing import List, Dict, Any, Optional, Tuple
import httpx

from agent.llm.usage import UsageLog


@lru_cache(maxsize=None)
def get_http_client(timeout: float) -> httpx.Client:
    """One pooled httpx.Client per distinct timeout, shared by every consumer.

    Building one costs ~200ms (a fresh SSLContext loading the certifi bundle)
    and the discarded one leaks its connection pool — a price every LLMClient()
    and every /model switch (two _init_client calls) used to pay.

    Long read budget for slow local models, short connect budget so an
    unreachable endpoint fails in seconds instead of minutes.
    """
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)))


@lru_cache(maxsize=1)
def _codex_exec_help() -> str:
    """`codex exec --help`, read once per process (spawning it costs ~1s)."""
    try:
        proc = subprocess.run(
            ["codex.cmd" if os.name == "nt" else "codex", "exec", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:  # not installed, wedged, or too old to have a --help
        return ""


def _codex_supports_resume() -> bool:
    """Only newer codex builds expose the `codex exec resume <session>` subcommand."""
    return re.search(r"^\s*resume\b", _codex_exec_help(), re.MULTILINE) is not None


# Codex renamed the approval bypass long ago; the name this file used until now
# ('--dangerously-bypass-approvals') is a hard `error: unexpected argument` on
# every current build, so openai-sub never got as far as reading its prompt.
CODEX_BYPASS_FLAG = "--dangerously-bypass-approvals-and-sandbox"


def _loads_lenient(text: str) -> Any:
    """json.loads, retried on the outermost {...} so a CLI banner above the
    payload does not lose us the structured result."""
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    return None


def _usage_namespace(data: Dict[str, Any]) -> Optional[SimpleNamespace]:
    """OpenAI-shaped usage from a CLI result JSON, or None when it reported none."""
    raw = data.get("usage")
    raw = raw if isinstance(raw, dict) else {}
    prompt = raw.get("input_tokens", raw.get("prompt_tokens"))
    completion = raw.get("output_tokens", raw.get("completion_tokens"))
    cost = data.get("total_cost_usd", data.get("cost_usd"))
    if prompt is None and completion is None and cost is None:
        return None
    usage = SimpleNamespace(
        prompt_tokens=prompt or 0,
        completion_tokens=completion or 0,
        total_tokens=(prompt or 0) + (completion or 0),
    )
    if cost is not None:
        usage.cost_usd = cost
    return usage


class BridgeSession:
    """Continuity state for one LLMClient talking to a subscription CLI.

    Holds the CLI's session id plus how much of the conversation it has already
    been given, so a resumed turn only has to carry the new messages. It resets
    itself — full transcript, fresh session — whenever the provider/model pin
    changes or the history stops being an extension of what was delivered
    (compaction and /rewind both rewrite or shorten it).
    """

    def __init__(self) -> None:
        self.key: Optional[Tuple[str, Optional[str]]] = None
        self.session_id: Optional[str] = None
        self.delivered: int = 0
        self.fingerprint: Optional[str] = None

    @staticmethod
    def _fingerprint(messages: List[Dict[str, Any]], count: int) -> Optional[str]:
        if count <= 0 or count > len(messages):
            return None
        m = messages[count - 1]
        return f"{m.get('role')}:{str(m.get('content'))[:200]}"

    def reset(self, key: Optional[Tuple[str, Optional[str]]] = None) -> None:
        self.key = key
        self.session_id = None
        self.delivered = 0
        self.fingerprint = None

    def delta(
        self, key: Tuple[str, Optional[str]], messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """(messages to send, session id to resume). A None session id means
        'send everything under a new session'."""
        if (
            self.key != key
            or len(messages) < self.delivered
            or self.fingerprint != self._fingerprint(messages, self.delivered)
        ):
            self.reset(key)
        if self.session_id and self.delivered:
            pending = list(messages[self.delivered :])
            # The CLI wrote the assistant turn itself; echoing it back is noise.
            while pending and pending[0].get("role") == "assistant":
                pending.pop(0)
            if pending:
                return pending, self.session_id
            self.reset(key)  # nothing new to say — replay the transcript instead
        return list(messages), None

    def record(self, messages: List[Dict[str, Any]], session_id: Optional[str]) -> None:
        self.session_id = session_id
        self.delivered = len(messages)
        self.fingerprint = self._fingerprint(messages, self.delivered)


class SubprocessSubscriptionBridge:
    """Dispatches chat completions to locally installed, authenticated CLI tools

    (Google Antigravity 'agy', Anthropic 'claude', OpenAI 'codex') using the user's
    active flat-rate monthly login session with zero API key requirement.
    """

    RESUME_PREAMBLE = (
        "(Continuing the same session: the workspace tools and the JSON tool-call "
        "format from the first message still apply. Emit one ```json block per "
        "tool call.)\n"
    )

    @staticmethod
    def _format_conversation_prompt(
        messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        prompt_parts = []
        if tools:
            tool_signatures = []
            for t in tools:
                fn = t.get("function", {})
                tool_signatures.append(
                    f"- {fn.get('name')}: {fn.get('description', '')}\n  Arguments schema: {json.dumps(fn.get('parameters', {}))}"
                )
            tools_spec = (
                "You have access to the following tools in this workspace:\n"
                + "\n".join(tool_signatures)
                + "\n\nWhen you need to use a tool, output one JSON block per call, each formatted exactly as:\n"
                '```json\n{"name": "<tool_name>", "arguments": {<args>}}\n```\n'
                "Several blocks in one reply run as several tool calls, in order.\n"
                "Otherwise, answer normally in markdown.\n"
            )
            prompt_parts.append(tools_spec)

        # Build transcript representation
        for m in messages:
            role = m.get("role", "user").upper()
            content = m.get("content") or ""
            if "tool_calls" in m:
                calls = m["tool_calls"]
                call_strs = [
                    f"Tool Call [{tc.get('function', {}).get('name')}]: {tc.get('function', {}).get('arguments')}"
                    for tc in calls
                ]
                content = (content + "\n" + "\n".join(call_strs)).strip()
            prompt_parts.append(f"[{role}]:\n{content}")

        prompt_parts.append("[ASSISTANT]:\n")
        return "\n\n".join(prompt_parts)

    @staticmethod
    def _parse_tool_calls(text: str) -> List[SimpleNamespace]:
        """Every ```json {"name":..., "arguments":...} block in the reply, in order.

        A CLI happily emits several calls plus prose around them; the old
        single-block split() dropped everything after the first one."""
        calls = []
        for block in re.findall(r"```json\s*(.*?)```", text, re.DOTALL):
            try:
                parsed = json.loads(block.strip())
            except (ValueError, TypeError):  # not a tool call; treat as prose
                continue
            if not (isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed):
                continue
            calls.append(
                SimpleNamespace(
                    id=f"call_sub_{os.getpid()}_{len(calls)}",
                    function=SimpleNamespace(
                        name=parsed["name"],
                        arguments=json.dumps(parsed["arguments"]),
                    ),
                )
            )
        return calls

    @classmethod
    def execute_turn(
        cls,
        provider: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: str = "medium",
        stream_callback: Optional[Any] = None,
        timeout: int = 180,
        model: Optional[str] = None,
        session: Optional[BridgeSession] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Any:
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Subscription CLI execution cancelled by user.")
        # No session object (a one-off caller) => a throwaway one, i.e. the old
        # behaviour: full transcript, new CLI session, every turn.
        session = session or BridgeSession()
        pending, resume_id = session.delta((provider, model), messages)
        if provider == "openai-sub" and resume_id and not _codex_supports_resume():
            pending, resume_id = list(messages), None

        prompt_text = (
            cls.RESUME_PREAMBLE + cls._format_conversation_prompt(pending, None)
            if resume_id
            else cls._format_conversation_prompt(pending, tools)
        )
        new_session_id: Optional[str] = None
        # claude -p can hand back a parseable result envelope; the others cannot.
        json_mode = provider == "anthropic-sub"
        # The transcript rides stdin wherever the CLI allows it: argv dies at
        # 8,191 chars on Windows .cmd shims ("The command line is too long")
        # and 32K for .exe, and a real conversation blows both. agy's print
        # mode documents no plain-text stdin path, so it keeps argv.
        stdin_text: Optional[str] = None

        if provider == "google-sub":
            # `agy --print` is one-shot — it exposes no session/resume flag — so
            # every turn re-sends the whole transcript.
            cmd = [
                "agy.exe" if os.name == "nt" else "agy",
                "--print",
                prompt_text,
                "--dangerously-skip-permissions",
                "--disable-slash-commands",
            ]
            if reasoning_effort in ("low", "medium", "high"):
                cmd.extend(["--effort", reasoning_effort])
            if model:
                cmd.extend(["--model", model])
        elif provider == "anthropic-sub":
            # No positional prompt: `claude -p` reads it from piped stdin.
            cmd = [
                "claude.exe" if os.name == "nt" else "claude",
                "-p",
                "--dangerously-skip-permissions",
                "--output-format",
                "json",
            ]
            stdin_text = prompt_text
            if resume_id:
                cmd.extend(["--resume", resume_id])
            else:
                new_session_id = str(uuid.uuid4())
                cmd.extend(["--session-id", new_session_id])
            if model:
                cmd.extend(["--model", model])
        elif provider == "openai-sub":
            cmd = ["codex.cmd" if os.name == "nt" else "codex", "exec"]
            if resume_id:
                cmd.extend(["resume", resume_id])
            # `-` = read the prompt from stdin (both exec and exec resume).
            cmd.extend(["-", CODEX_BYPASS_FLAG])
            stdin_text = prompt_text
            if model:
                cmd.extend(["-m", model])
            if reasoning_effort in ("low", "medium", "high"):
                cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        else:
            raise ValueError(f"Unknown subscription provider: {provider}")

        # In json mode the child streams one machine-readable blob, so the live
        # channel gets the parsed answer once instead of a wall of JSON.
        live_callback = None if json_mode else stream_callback

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_text is not None else None,
                stdout=subprocess.PIPE,
                # Merged rather than a second pipe: stdout was streamed line by
                # line while stderr sat unread, so a chatty CLI filled the stderr
                # buffer and both sides deadlocked.
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            if stdin_text is not None and proc.stdin:
                try:
                    proc.stdin.write(stdin_text)
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass  # child died early; the read loop will surface why
                # POSIX communicate() registers self.stdin with a selector when
                # it is not None — on a closed file that raises 'I/O operation
                # on closed file'. Detach it so communicate() skips stdin.
                proc.stdin = None
            # The read loop blocks until the child closes stdout, so the deadline
            # has to kill the child — a communicate(timeout=) below it never runs.
            expired = []
            cancelled = []

            def _kill_expired():
                expired.append(True)
                proc.kill()

            killer = threading.Timer(timeout, _kill_expired)
            killer.start()
            cancel_done = threading.Event()
            cancel_waiter = None
            if cancel_event is not None:

                def _kill_cancelled():
                    while not cancel_done.wait(0.05):
                        if cancel_event.is_set():
                            cancelled.append(True)
                            proc.kill()
                            return

                cancel_waiter = threading.Thread(target=_kill_cancelled, daemon=True)
                cancel_waiter.start()
            try:
                raw_lines = []
                if proc.stdout:
                    for line in proc.stdout:
                        raw_lines.append(line)
                        if live_callback:
                            live_callback(line)
                stdout_remainder, _ = proc.communicate()
            finally:
                killer.cancel()
                cancel_done.set()
                if cancel_waiter:
                    cancel_waiter.join(timeout=1)

            if cancelled:
                raise RuntimeError(f"Subscription CLI for '{provider}' was cancelled by user.")
            if expired:
                raise RuntimeError(
                    f"Subscription CLI for '{provider}' produced no result within "
                    f"{timeout}s and was terminated."
                )
            if stdout_remainder:
                raw_lines.append(stdout_remainder)
                if live_callback:
                    live_callback(stdout_remainder)

            raw_output = "".join(raw_lines).strip()
            if proc.returncode != 0:
                detail = raw_output[-1000:] if raw_output else "no diagnostic output"
                raise RuntimeError(
                    "Subscription CLI execution failed: "
                    f"process exited with code {proc.returncode}: {detail}"
                )
        except FileNotFoundError:
            raise RuntimeError(
                f"Native CLI executable for '{provider}' not found on PATH. "
                "Ensure it is installed or switch to API / Local mode via /model."
            )

        cleaned_content = raw_output
        usage = None
        if json_mode:
            data = _loads_lenient(raw_output)
            if isinstance(data, dict) and data.get("is_error"):
                raise RuntimeError(
                    "Subscription CLI reported an error: "
                    + str(data.get("result") or data.get("error") or "unknown error")[:1000]
                )
            if isinstance(data, dict) and "result" in data:
                cleaned_content = data.get("result") or ""
                new_session_id = data.get("session_id") or new_session_id
                usage = _usage_namespace(data)
            # else: an unparseable banner/plain text — keep the raw output.
            if stream_callback and cleaned_content:
                stream_callback(cleaned_content)
        elif provider == "openai-sub":
            found = re.search(
                r"session[ _-]?id\D{0,3}([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})",
                raw_output,
                re.IGNORECASE,
            )
            new_session_id = found.group(1) if found else None

        session.record(messages, new_session_id)

        tool_calls = cls._parse_tool_calls(cleaned_content)

        # Format into OpenAI-compatible response namespace
        msg_obj = SimpleNamespace(
            content=cleaned_content,
            tool_calls=tool_calls if tool_calls else None,
        )
        choice_obj = SimpleNamespace(message=msg_obj)
        return SimpleNamespace(choices=[choice_obj], usage=usage)


class LLMConfig:
    # Comprehensive Frontier Subscription Presets with accurate context windows
    PRESETS: Dict[str, Dict[str, Any]] = {
        # --- Native Monthly Subscriptions (Zero API Key / OAuth CLI) ---
        "sub-google-antigravity": {
            "name": "🌟 Google Antigravity (Logged-In Monthly Subscription)",
            "provider": "google-sub",
            "model": "google-antigravity-subscription",
            "base_url": "subscription://agy",
            "api_key_env": None,
            "default_effort": "medium",
            "context_window": 2000000,
        },
        "sub-claude-code": {
            "name": "⚡ Anthropic Claude Code (Logged-In Monthly Subscription)",
            "provider": "anthropic-sub",
            "model": "claude-code-subscription",
            "base_url": "subscription://claude",
            "api_key_env": None,
            "default_effort": "high",
            "context_window": 200000,
        },
        "sub-openai-codex": {
            "name": "🧠 OpenAI Codex (Logged-In Monthly Subscription)",
            "provider": "openai-sub",
            "model": "openai-codex-subscription",
            "base_url": "subscription://codex",
            "api_key_env": None,
            "default_effort": "high",
            "context_window": 200000,
        },
        # --- Google Antigravity (Gemini API Key) ---
        "agy-flash-3.7": {
            "name": "Google Antigravity Flash (Gemini 3.7 Flash - Developer API Key)",
            "provider": "google",
            "model": "gemini-3.7-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key_env": "GEMINI_API_KEY",
            "alt_api_key_envs": ["GOOGLE_API_KEY"],
            "default_effort": "low",
            "context_window": 1000000,
        },
        "agy-pro-3.1": {
            "name": "Google Antigravity Pro (Gemini 3.1 Pro - Developer API Key)",
            "provider": "google",
            "model": "gemini-3.1-pro",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key_env": "GEMINI_API_KEY",
            "alt_api_key_envs": ["GOOGLE_API_KEY"],
            "default_effort": "high",
            "context_window": 2000000,
        },
        "agy-flash-3.6": {
            "name": "Google Antigravity Flash (Gemini 3.6 Flash - Developer API Key)",
            "provider": "google",
            "model": "gemini-3.6-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key_env": "GEMINI_API_KEY",
            "alt_api_key_envs": ["GOOGLE_API_KEY"],
            "default_effort": "low",
            "context_window": 1000000,
        },
        # --- Anthropic (Claude Developer API Key) ---
        "claude-sonnet-5": {
            "name": "Claude Code Sonnet 5 (Developer API Key)",
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_effort": "high",
            "context_window": 200000,
        },
        "claude-opus-5": {
            "name": "Claude Code Opus 5 (Developer API Key)",
            "provider": "anthropic",
            "model": "claude-opus-5",
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_effort": "high",
            "context_window": 200000,
        },
        "claude-fable-5": {
            "name": "Claude Code Fable 5 (Developer API Key)",
            "provider": "anthropic",
            "model": "claude-fable-5",
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_effort": "high",
            "context_window": 200000,
        },
        "claude-haiku-4.5": {
            "name": "Claude Code Haiku 4.5 (Developer API Key)",
            "provider": "anthropic",
            "model": "claude-haiku-4.5",
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_effort": "low",
            "context_window": 200000,
        },
        # --- OpenAI Codex (Developer API Key) ---
        "codex-gpt-5.6-sol": {
            "name": "OpenAI Codex GPT-5.6 Sol (Developer API Key)",
            "provider": "openai",
            "model": "gpt-5.6-sol",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "high",
            "context_window": 200000,
        },
        "codex-gpt-5.6-terra": {
            "name": "OpenAI Codex GPT-5.6 Terra (Developer API Key)",
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "medium",
            "context_window": 200000,
        },
        "codex-gpt-5.6-luna": {
            "name": "OpenAI Codex GPT-5.6 Luna (Developer API Key)",
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "low",
            "context_window": 200000,
        },
        "codex-o3-pro": {
            "name": "OpenAI Codex o3-pro (Developer API Key)",
            "provider": "openai",
            "model": "o3-pro",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "high",
            "context_window": 200000,
        },
        "codex-o4-mini": {
            "name": "OpenAI Codex o4-mini (Developer API Key)",
            "provider": "openai",
            "model": "o4-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "medium",
            "context_window": 128000,
        },
        # --- DeepSeek (V4 & R-Series) ---
        "deepseek-v4-pro": {
            "name": "DeepSeek V4-Pro (Developer API Key)",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "default_effort": "high",
            "context_window": 128000,
        },
        "deepseek-v4-flash": {
            "name": "DeepSeek V4-Flash (Developer API Key)",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "default_effort": "low",
            "context_window": 128000,
        },
        "deepseek-r1": {
            "name": "DeepSeek R1 (Developer API Key)",
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "default_effort": "high",
            "context_window": 128000,
        },
        # --- Local Offline ---
        "local-lmstudio": {
            "name": "Local LM Studio / Ollama (Offline Free Qwen/Llama/DeepSeek)",
            "provider": "local",
            "model": "local-model",
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "LLM_API_KEY",
            "default_effort": "low",
            "context_window": 32768,
        },
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        reasoning_effort: str = "medium",  # "low", "medium", "high"
        provider: str = "local",
        context_window: Optional[int] = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
    ):
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "lm-studio")
        self.model = model or os.getenv("LLM_MODEL", "local-model")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.provider = provider
        self.context_window = context_window or 32768
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        # Concrete model handed to a subscription CLI (--model); None = CLI default.
        self.sub_model: Optional[str] = None
        # The preset this config came from, for the usage journal's per-preset
        # bucket. None whenever the model was set by hand rather than by preset.
        self.preset_key: Optional[str] = None

    @staticmethod
    def preset_available(preset: Dict[str, Any], include_local: bool = False) -> bool:
        """Whether a preset has its local prerequisite without a network call."""
        provider = str(preset.get("provider", "local"))
        if provider.endswith("-sub"):
            cli = str(preset.get("base_url", "")).split("://")[-1]
            return bool(cli and shutil.which(cli))
        if provider == "local":
            return include_local
        envs = [preset.get("api_key_env")] + list(preset.get("alt_api_key_envs") or [])
        return any(name and os.getenv(name) for name in envs)

    @classmethod
    def from_preset(
        cls,
        preset_key: str,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> "LLMConfig":
        """Build an independent config from the canonical preset table."""
        try:
            preset = cls.PRESETS[preset_key]
        except KeyError as exc:
            raise ValueError(f"unknown preset '{preset_key}'") from exc
        key = None
        envs = [preset.get("api_key_env")] + list(preset.get("alt_api_key_envs") or [])
        for env_name in envs:
            if env_name and os.getenv(env_name):
                key = os.getenv(env_name)
                break
        if preset["provider"] == "local":
            key = key or "lm-studio"
        subscription = str(preset["provider"]).endswith("-sub")
        config = cls(
            base_url=base_url or preset["base_url"],
            api_key=key,
            model=preset["model"] if subscription else model or preset["model"],
            reasoning_effort=reasoning_effort or preset.get("default_effort", "medium"),
            provider=preset["provider"],
            context_window=preset.get("context_window", 32768),
        )
        # __init__ has a generic LLM_API_KEY fallback for ad-hoc local clients.
        # A preset must retain only its provider-specific credential resolution.
        config.api_key = key
        config.preset_key = preset_key
        if subscription:
            config.sub_model = model
        return config

    @classmethod
    def sub_models(cls, preset_key: str) -> List[str]:
        """Models a subscription preset can run: the API-key presets of the same
        vendor (sub-claude-code -> claude-fable-5, claude-opus-5, ...)."""
        preset = cls.PRESETS.get(preset_key) or {}
        provider = str(preset.get("provider", ""))
        if not provider.endswith("-sub"):
            return []
        vendor = provider[: -len("-sub")]
        return [str(p["model"]) for p in cls.PRESETS.values() if p.get("provider") == vendor]

    def display_model(self) -> str:
        return f"{self.model}/{self.sub_model}" if self.sub_model else self.model


class LLMClient:
    # Models that accept the OpenAI-compatible `reasoning_effort` request field.
    EFFORT_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gemini-3")
    TRANSIENT_STATUS_CODES = (408, 409, 425, 429, 500, 502, 503, 504)

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        # Continuity for subscription CLIs; it re-keys itself on provider/model
        # changes, so /model switches need no explicit reset here.
        self.bridge_session = BridgeSession()
        # ponytail: cwd-scoped; thread a workspace_root through if the agent ever
        # runs outside it. Both entrypoints are chdir-free, so cwd == workspace root.
        self.usage = UsageLog()
        self._init_client()

    def _init_client(self):
        # Imported lazily: pulling in the openai SDK costs ~400ms, which every
        # `--help`/`--version` run and every subscription-provider session would
        # otherwise pay for a client it never builds.
        from openai import OpenAI

        if not self.config.provider.endswith("-sub"):
            self.client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key or "local",
                http_client=get_http_client(self.config.timeout),
                max_retries=0,  # retries are owned by _with_retry below
            )
        else:
            self.client = None

    @classmethod
    def effort_supported(cls, provider: str, model: str) -> bool:
        """True when (provider, model) actually forwards reasoning effort to the backend."""
        if provider == "google-sub":
            return True  # passed as `--effort` to the agy CLI
        if provider == "openai-sub":
            return True  # passed as `-c model_reasoning_effort=...` to codex exec
        if provider.endswith("-sub"):
            return False
        return model.startswith(cls.EFFORT_MODEL_PREFIXES)

    def supports_reasoning_effort(self) -> bool:
        return self.effort_supported(self.config.provider, self.config.model)

    def _effort_note(self) -> str:
        effort = self.config.reasoning_effort.upper()
        if self.supports_reasoning_effort():
            return f"Effort: {effort}"
        return f"Effort: {effort} (not supported by this model — ignored)"

    def _is_transient(self, exc: Exception) -> bool:
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )
        if status in self.TRANSIENT_STATUS_CODES:
            return True
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return False
        return any(
            k in name
            for k in (
                "connection",
                "ratelimit",
                "internalserver",
                "apierror",
            )
        )

    def _with_retry(self, call: Any):
        """Bounded retry with exponential backoff on transient failures."""
        attempts = max(1, self.config.max_retries)
        last_err: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                return call()
            except Exception as e:
                if not self._is_transient(e):
                    raise
                last_err = e
                if attempt < attempts - 1:
                    time.sleep(self.config.retry_backoff * (2**attempt))
        raise RuntimeError(
            f"LLM request to '{self.config.model}' via provider '{self.config.provider}' "
            f"failed after {attempts} attempt(s): {last_err}"
        ) from last_err

    def switch_model(
        self,
        preset_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        sub_model: Optional[str] = None,
    ) -> str:
        """Switch active model configuration or load from subscription presets.

        `sub_model` picks the concrete model a subscription CLI runs (e.g.
        'claude-fable-5' under sub-claude-code); ignored for non-subscription presets."""
        from agent.governance.context import context_manager

        if preset_key and preset_key in LLMConfig.PRESETS:
            preset = LLMConfig.PRESETS[preset_key]

            env_key = preset.get("api_key_env")
            found_key = None
            if env_key and os.getenv(env_key):
                found_key = os.getenv(env_key)
            else:
                for alt in preset.get("alt_api_key_envs", []):
                    if os.getenv(alt):
                        found_key = os.getenv(alt)
                        break

            key = found_key or api_key
            if not key and preset["provider"] == "local":
                # Local endpoints ignore the key, but must never inherit the
                # previous provider's one either.
                key = "lm-studio"
            if not key and not preset["provider"].endswith("-sub"):
                # Switching anyway would silently send the PREVIOUS provider's key
                # to a new endpoint and report success.
                names = " or ".join(
                    n for n in [env_key] + list(preset.get("alt_api_key_envs", [])) if n
                )
                self.config.api_key = None
                return (
                    f"Cannot switch to '{preset['name']}': no API key found. "
                    f"Set {names} in your .env, or pass one explicitly. "
                    f"Still on '{self.config.model}'."
                )

            self.config.model = preset["model"]
            self.config.preset_key = preset_key
            self.config.base_url = preset["base_url"]
            self.config.provider = preset["provider"]
            self.config.context_window = preset.get("context_window", 32768)
            context_manager.set_max_tokens(self.config.context_window)
            self.config.api_key = key
            self.config.sub_model = (
                sub_model if preset["provider"].endswith("-sub") and sub_model else None
            )

            if reasoning_effort:
                self.config.reasoning_effort = reasoning_effort
            else:
                self.config.reasoning_effort = preset.get("default_effort", "medium")
            self._init_client()
            via = f" running {self.config.sub_model}" if self.config.sub_model else ""
            return f"Switched to preset '{preset['name']}'{via} ({self._effort_note()}, Context: {self.config.context_window:,} tokens)"

        if model:
            self.config.model = model
            # A hand-set model is no longer that preset — the journal must not keep
            # billing the old preset's bucket for it.
            self.config.preset_key = None
        if base_url:
            self.config.base_url = base_url
        if api_key:
            self.config.api_key = api_key
        if reasoning_effort:
            self.config.reasoning_effort = reasoning_effort
        self._init_client()
        return f"Updated model configuration: {self.config.model} ({self._effort_note()})"

    def _record(self, t0: float, response: Any, ok: bool = True, error: Optional[str] = None):
        """Append this call to .agnostic/usage.jsonl. Every path through
        chat_completion — success or failure, API or subscription bridge — ends
        here, and a broken journal must never take a turn down with it."""
        try:
            self.usage.record_response(
                getattr(self.config, "preset_key", None),
                self.config,
                response,
                time.monotonic() - t0,
                ok=ok,
                error=error,
            )
        except Exception:
            pass

    def chat_completion(  # called by AgentLoop/subagents; single-file scans miss it
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
        stream_callback: Optional[Any] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        """Invoke chat completion with tool calling, live streaming, and reasoning effort support."""
        if self.config.provider.endswith("-sub"):
            t0 = time.monotonic()
            try:
                resp = SubprocessSubscriptionBridge.execute_turn(
                    provider=self.config.provider,
                    messages=messages,
                    tools=tools,
                    reasoning_effort=self.config.reasoning_effort,
                    model=self.config.sub_model,
                    stream_callback=stream_callback,
                    session=self.bridge_session,
                    cancel_event=cancel_event,
                )
            except Exception as e:
                self._record(t0, None, ok=False, error=str(e)[:200])
                raise
            self._record(t0, resp)
            return resp

        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": self.config.timeout,
        }

        # Inject reasoning_effort only for models that actually accept it
        if self.supports_reasoning_effort():
            kwargs["reasoning_effort"] = self.config.reasoning_effort

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if stream or stream_callback is not None:
            # Ask for the trailing usage chunk — without it a streamed turn records
            # zero tokens and no cost. LM Studio / Ollama builds reject unknown
            # request fields outright, so local endpoints never see it.
            if self.config.provider != "local":
                kwargs["stream_options"] = {"include_usage": True}
            t0 = time.monotonic()
            try:
                # Stream tokens live.
                # ponytail: retry covers request setup only; a mid-stream drop is surfaced
                # to the caller rather than replayed (would duplicate emitted tokens).
                response_stream = self._with_retry(
                    lambda: self.client.chat.completions.create(stream=True, **kwargs)
                )
                collected_chunks = []
                tool_calls_dict = {}
                finish_reason = None
                stream_usage = None

                for chunk in response_stream:
                    if cancel_event and cancel_event.is_set():
                        close = getattr(response_stream, "close", None)
                        if close:
                            close()
                        raise RuntimeError("LLM request cancelled by user.")
                    # BEFORE the empty-choices guard on purpose: OpenAI-compatible
                    # servers send the usage chunk with an EMPTY choices list, so
                    # skipping it first threw the token counts away.
                    if getattr(chunk, "usage", None):
                        stream_usage = chunk.usage
                    if not chunk.choices or len(chunk.choices) == 0:
                        continue
                    if chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                    delta = chunk.choices[0].delta
                    if delta.content:
                        collected_chunks.append(delta.content)
                        if stream_callback:
                            stream_callback(delta.content)

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc.id or f"call_{idx}",
                                    "name": tc.function.name if tc.function else "",
                                    "arguments": tc.function.arguments or "" if tc.function else "",
                                }
                            else:
                                if tc.function and tc.function.name:
                                    tool_calls_dict[idx]["name"] += tc.function.name
                                if tc.function and tc.function.arguments:
                                    tool_calls_dict[idx]["arguments"] += tc.function.arguments

                full_content = "".join(collected_chunks)
                tool_calls_list = []
                for idx in sorted(tool_calls_dict.keys()):
                    tc_data = tool_calls_dict[idx]
                    tool_calls_list.append(
                        SimpleNamespace(
                            id=tc_data["id"],
                            function=SimpleNamespace(
                                name=tc_data["name"],
                                arguments=tc_data["arguments"],
                            ),
                        )
                    )

                msg_obj = SimpleNamespace(
                    content=full_content,
                    tool_calls=tool_calls_list if tool_calls_list else None,
                )
                response = SimpleNamespace(
                    choices=[SimpleNamespace(message=msg_obj, finish_reason=finish_reason)],
                    usage=stream_usage,
                )
            except Exception as e:
                self._record(t0, None, ok=False, error=str(e)[:200])
                raise
            self._record(t0, response)
            return response

        t0 = time.monotonic()
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("LLM request cancelled by user.")
        try:
            response = self._with_retry(lambda: self.client.chat.completions.create(**kwargs))
        except Exception as e:
            self._record(t0, None, ok=False, error=str(e)[:200])
            raise
        self._record(t0, response)
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("LLM request cancelled by user.")
        return response
