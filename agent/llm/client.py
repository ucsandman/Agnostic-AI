"""
agent/llm/client.py — Universal LLM Client Adapter
Supports LM Studio (localhost:1234), Ollama (localhost:11434), OpenAI, vLLM, DeepSeek, Claude, and Gemini endpoints.
"""

import os
from typing import List, Dict, Any, Optional
from openai import OpenAI


class LLMConfig:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ):
        # Default to local LM Studio if not specified
        self.base_url = base_url or os.getenv(
            "LLM_BASE_URL", "http://localhost:1234/v1"
        )
        self.api_key = api_key or os.getenv("LLM_API_KEY", "lm-studio")
        self.model = model or os.getenv("LLM_MODEL", "local-model")
        self.temperature = temperature
        self.max_tokens = max_tokens


class LLMClient:
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self.client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        stream: bool = False,
    ):
        """Invoke chat completion with tool calling support."""
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if stream:
            return self.client.chat.completions.create(stream=True, **kwargs)
        else:
            return self.client.chat.completions.create(**kwargs)
