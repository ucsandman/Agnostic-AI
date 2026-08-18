"""
agent/llm/client.py — Universal LLM Client Adapter
Supports LM Studio (localhost:1234), Ollama (localhost:11434), OpenAI, vLLM, DeepSeek, Claude, and Gemini endpoints.
"""

import os
from typing import List, Dict, Any, Optional
from openai import OpenAI


class LLMConfig:
    # Popular subscription presets
    PRESETS: Dict[str, Dict[str, Any]] = {
        "agy-flash": {
            "name": "Google Antigravity Flash (Gemini 3.7 Flash)",
            "provider": "google",
            "model": "gemini-3.7-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key_env": "GEMINI_API_KEY",
            "default_effort": "low",
        },
        "agy-pro": {
            "name": "Google Antigravity Pro (Gemini 3.7 Pro Thinking)",
            "provider": "google",
            "model": "gemini-3.7-pro",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key_env": "GEMINI_API_KEY",
            "default_effort": "high",
        },
        "claude-sonnet": {
            "name": "Claude Code Sonnet (Claude 3.7 Sonnet Thinking)",
            "provider": "anthropic",
            "model": "claude-3-7-sonnet-latest",
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_effort": "high",
        },
        "claude-haiku": {
            "name": "Claude Code Haiku (Claude 3.5 Haiku)",
            "provider": "anthropic",
            "model": "claude-3-5-haiku-latest",
            "base_url": "https://api.anthropic.com/v1",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_effort": "low",
        },
        "codex-o3-mini": {
            "name": "OpenAI Codex o3-mini (High Reasoning)",
            "provider": "openai",
            "model": "o3-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "high",
        },
        "codex-o1": {
            "name": "OpenAI Codex o1 (Deep Research / Max Effort)",
            "provider": "openai",
            "model": "o1",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "high",
        },
        "codex-gpt-4o": {
            "name": "OpenAI Codex GPT-4o (Fast Multimodal)",
            "provider": "openai",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "default_effort": "medium",
        },
        "deepseek-r1": {
            "name": "DeepSeek R1 Reasoning (vLLM / OpenRouter)",
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "default_effort": "high",
        },
        "local-lmstudio": {
            "name": "Local LM Studio / Ollama (Offline Free)",
            "provider": "local",
            "model": "local-model",
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "LLM_API_KEY",
            "default_effort": "low",
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
    ):
        self.base_url = base_url or os.getenv(
            "LLM_BASE_URL", "http://localhost:1234/v1"
        )
        self.api_key = api_key or os.getenv("LLM_API_KEY", "lm-studio")
        self.model = model or os.getenv("LLM_MODEL", "local-model")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.provider = provider


class LLMClient:
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._init_client()

    def _init_client(self):
        self.client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    def switch_model(
        self,
        preset_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> str:
        """Switch active model configuration or load from subscription presets."""
        if preset_key and preset_key in LLMConfig.PRESETS:
            preset = LLMConfig.PRESETS[preset_key]
            self.config.model = preset["model"]
            self.config.base_url = preset["base_url"]
            self.config.provider = preset["provider"]
            env_key = preset.get("api_key_env")
            if env_key and os.getenv(env_key):
                self.config.api_key = os.getenv(env_key)
            elif api_key:
                self.config.api_key = api_key
            if reasoning_effort:
                self.config.reasoning_effort = reasoning_effort
            else:
                self.config.reasoning_effort = preset.get("default_effort", "medium")
            self._init_client()
            return f"Switched to preset '{preset['name']}' (Effort: {self.config.reasoning_effort.upper()})"

        if model:
            self.config.model = model
        if base_url:
            self.config.base_url = base_url
        if api_key:
            self.config.api_key = api_key
        if reasoning_effort:
            self.config.reasoning_effort = reasoning_effort
        self._init_client()
        return f"Updated model configuration: {self.config.model} (Effort: {self.config.reasoning_effort.upper()})"

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
    ):
        """Invoke chat completion with tool calling and reasoning effort support."""
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        # Inject reasoning_effort if supported (e.g. OpenAI o1/o3-mini or Gemini 3.7)
        if self.config.model.startswith(("o1", "o3", "gemini-3.7")):
            kwargs["reasoning_effort"] = self.config.reasoning_effort

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if stream:
            return self.client.chat.completions.create(stream=True, **kwargs)
        else:
            return self.client.chat.completions.create(**kwargs)
