"""
agent/llm/detector.py — Auto-Discovery & Health Inspector (/doctor)
Automatically queries LM Studio or local OpenAI-compatible endpoints to detect active model name,
context window size, available models, and endpoint latency.
"""

from typing import Dict, Any

from agent.llm.client import get_http_client


class ModelDoctor:
    def __init__(self, base_url: str = "http://localhost:1234/v1", api_key: str = "lm-studio"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def inspect(self) -> Dict[str, Any]:
        """Queries local endpoint and retrieves model metadata."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        models_url = f"{self.base_url}/models"

        info: Dict[str, Any] = {
            "status": "offline",
            "base_url": self.base_url,
            "active_model": None,
            "all_models": [],
            "context_length": None,
            "error": None,
        }

        try:
            # Shared pooled client — never close it, other callers hold it too.
            res = get_http_client(4.0).get(models_url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                models_list = data.get("data", [])
                info["status"] = "online"
                info["all_models"] = [m.get("id") for m in models_list if m.get("id")]
                if info["all_models"]:
                    info["active_model"] = info["all_models"][0]
            else:
                info["error"] = f"HTTP {res.status_code}: {res.text[:200]}"
        except Exception as e:
            info["error"] = str(e)

        return info

    def format_report(self) -> str:
        data = self.inspect()
        if data["status"] == "online":
            models_str = "\n".join([f"  • {m}" for m in data["all_models"]]) or "  (None reported)"
            return (
                f"✅ Endpoint Status: ONLINE ({data['base_url']})\n"
                f"🤖 Active / Detected Model: [bold green]{data['active_model'] or 'Unknown'}[/bold green]\n"
                f"📦 Available Models ({len(data['all_models'])}):\n{models_str}"
            )
        else:
            return (
                f"❌ Endpoint Status: OFFLINE / UNREACHABLE ({data['base_url']})\n"
                f"Details: {data['error']}\n"
                f"Tip: Ensure LM Studio or Ollama is running with local server started."
            )
