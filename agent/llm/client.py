"""
agent/llm/client.py — Universal LLM Client Adapter
Supports LM Studio (localhost:1234), Ollama (localhost:11434), OpenAI, vLLM, DeepSeek, Claude, and Gemini endpoints.
"""

import os
import json
import time
import subprocess
from types import SimpleNamespace
from typing import List, Dict, Any, Optional
import httpx


class SubprocessSubscriptionBridge:
    """Dispatches chat completions to locally installed, authenticated CLI tools

    (Google Antigravity 'agy', Anthropic 'claude', OpenAI 'codex') using the user's
    active flat-rate monthly login session with zero API key requirement.
    """

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
                + "\n\nWhen you need to use a tool, output a single JSON block formatted exactly as:\n"
                '```json\n{"name": "<tool_name>", "arguments": {<args>}}\n```\n'
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

    @classmethod
    def execute_turn(
        cls,
        provider: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: str = "medium",
        stream_callback: Optional[Any] = None,
    ) -> Any:
        prompt_text = cls._format_conversation_prompt(messages, tools)

        if provider == "google-sub":
            cmd = [
                "agy.exe" if os.name == "nt" else "agy",
                "--print",
                prompt_text,
                "--dangerously-skip-permissions",
                "--disable-slash-commands",
            ]
            if reasoning_effort in ("low", "medium", "high"):
                cmd.extend(["--effort", reasoning_effort])
        elif provider == "anthropic-sub":
            cmd = [
                "claude.exe" if os.name == "nt" else "claude",
                "-p",
                prompt_text,
                "--dangerously-skip-permissions",
            ]
        elif provider == "openai-sub":
            cmd = [
                "codex.cmd" if os.name == "nt" else "codex",
                "exec",
                prompt_text,
                "--dangerously-bypass-approvals",
            ]
        else:
            raise ValueError(f"Unknown subscription provider: {provider}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            raw_lines = []
            if proc.stdout:
                for line in proc.stdout:
                    raw_lines.append(line)
                    if stream_callback:
                        stream_callback(line)
            stdout_remainder, stderr = proc.communicate(timeout=180)
            if stdout_remainder:
                raw_lines.append(stdout_remainder)
                if stream_callback:
                    stream_callback(stdout_remainder)

            raw_output = "".join(raw_lines).strip()
            if proc.returncode != 0 and not raw_output:
                err_text = stderr.strip() or f"Process exited with code {proc.returncode}"
                raise RuntimeError(f"Subscription CLI execution failed: {err_text}")
        except FileNotFoundError:
            raise RuntimeError(
                f"Native CLI executable for '{provider}' not found on PATH. "
                "Ensure it is installed or switch to API / Local mode via /model."
            )

        # Parse potential tool calls from JSON block
        tool_calls = []
        cleaned_content = raw_output

        json_match = None
        if "```json" in raw_output and "```" in raw_output.split("```json", 1)[1]:
            raw_json_str = raw_output.split("```json", 1)[1].split("```", 1)[0].strip()
            try:
                parsed = json.loads(raw_json_str)
                if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
                    json_match = parsed
            except (ValueError, TypeError, json.JSONDecodeError):  # not a tool call; treat as prose
                pass

        if json_match:
            tool_calls.append(
                SimpleNamespace(
                    id="call_sub_" + str(int(subprocess.os.getpid())),
                    function=SimpleNamespace(
                        name=json_match["name"],
                        arguments=json.dumps(json_match["arguments"]),
                    ),
                )
            )

        # Format into OpenAI-compatible response namespace
        msg_obj = SimpleNamespace(
            content=cleaned_content,
            tool_calls=tool_calls if tool_calls else None,
        )
        choice_obj = SimpleNamespace(message=msg_obj)
        return SimpleNamespace(choices=[choice_obj])


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


class LLMClient:
    # Models that accept the OpenAI-compatible `reasoning_effort` request field.
    EFFORT_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gemini-3")
    TRANSIENT_STATUS_CODES = (408, 409, 425, 429, 500, 502, 503, 504)

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
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
                # Long read budget for slow local models, short connect budget so
                # an unreachable endpoint fails in seconds instead of minutes.
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                max_retries=0,  # retries are owned by _with_retry below
            )
        else:
            self.client = None

    def supports_reasoning_effort(self) -> bool:
        """True when the active preset actually forwards reasoning effort to the backend."""
        if self.config.provider == "google-sub":
            return True  # passed as `--effort` to the agy CLI
        if self.config.provider.endswith("-sub"):
            return False
        return self.config.model.startswith(self.EFFORT_MODEL_PREFIXES)

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
    ) -> str:
        """Switch active model configuration or load from subscription presets."""
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
            self.config.base_url = preset["base_url"]
            self.config.provider = preset["provider"]
            self.config.context_window = preset.get("context_window", 32768)
            context_manager.set_max_tokens(self.config.context_window)
            self.config.api_key = key

            if reasoning_effort:
                self.config.reasoning_effort = reasoning_effort
            else:
                self.config.reasoning_effort = preset.get("default_effort", "medium")
            self._init_client()
            return f"Switched to preset '{preset['name']}' ({self._effort_note()}, Context: {self.config.context_window:,} tokens)"

        if model:
            self.config.model = model
        if base_url:
            self.config.base_url = base_url
        if api_key:
            self.config.api_key = api_key
        if reasoning_effort:
            self.config.reasoning_effort = reasoning_effort
        self._init_client()
        return f"Updated model configuration: {self.config.model} ({self._effort_note()})"

    def chat_completion(  # noqa: vulture
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
        stream_callback: Optional[Any] = None,
    ):
        """Invoke chat completion with tool calling, live streaming, and reasoning effort support."""
        if self.config.provider.endswith("-sub"):
            return SubprocessSubscriptionBridge.execute_turn(
                provider=self.config.provider,
                messages=messages,
                tools=tools,
                reasoning_effort=self.config.reasoning_effort,
                stream_callback=stream_callback,
            )

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
            # Stream tokens live.
            # ponytail: retry covers request setup only; a mid-stream drop is surfaced
            # to the caller rather than replayed (would duplicate emitted tokens).
            response_stream = self._with_retry(
                lambda: self.client.chat.completions.create(stream=True, **kwargs)
            )
            collected_chunks = []
            tool_calls_dict = {}
            finish_reason = None

            for chunk in response_stream:
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
            return SimpleNamespace(
                choices=[SimpleNamespace(message=msg_obj, finish_reason=finish_reason)]
            )
        else:
            return self._with_retry(lambda: self.client.chat.completions.create(**kwargs))
