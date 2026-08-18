"""
agent/governance/context.py — Context Window Estimator, Meter & Auto-Compaction
Calculates approximate token usage across messages and handles graceful background compaction.
"""

import json
from typing import List, Dict, Any, Tuple


class ContextManager:
    def __init__(
        self, max_context_tokens: int = 16384, compaction_threshold: float = 0.75
    ):
        self.max_context_tokens = max_context_tokens
        self.compaction_threshold = compaction_threshold

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Estimate token count across conversation history (~4 chars per token)."""
        total_chars = 0
        for msg in messages:
            content = msg.get("content") or ""
            total_chars += len(content)
            if "tool_calls" in msg:
                total_chars += len(json.dumps(msg["tool_calls"]))
        return max(1, total_chars // 4)

    def get_status(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        used_tokens = self.estimate_tokens(messages)
        pct = min(100.0, (used_tokens / self.max_context_tokens) * 100.0)
        near_limit = pct >= (self.compaction_threshold * 100.0)
        return {
            "used_tokens": used_tokens,
            "max_tokens": self.max_context_tokens,
            "percentage": pct,
            "near_limit": near_limit,
        }

    def render_gauge(self, messages: List[Dict[str, Any]]) -> str:
        st = self.get_status(messages)
        pct = st["percentage"]
        used = st["used_tokens"]
        total = st["max_tokens"]

        # Build 16-segment visual progress bar
        total_blocks = 16
        filled_blocks = min(total_blocks, int((pct / 100.0) * total_blocks))
        empty_blocks = total_blocks - filled_blocks

        bar_color = "green" if pct < 60 else "yellow" if pct < 80 else "red"
        bar = "█" * filled_blocks + "░" * empty_blocks

        return f"[{bar_color}]Context: [{bar}] {pct:.1f}% ({used:,} / {total:,} tokens)[/{bar_color}]"

    def auto_compact(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], bool, str]:
        """Compacts older turns if context exceeds threshold."""
        st = self.get_status(messages)
        if not st["near_limit"] or len(messages) <= 4:
            return messages, False, ""

        system_msg = (
            messages[0]
            if messages and messages[0]["role"] == "system"
            else {"role": "system", "content": "You are an autonomous AI coding agent."}
        )
        recent_turns = messages[-4:]  # Retain last 4 turns verbatim
        middle_turns = messages[1:-4]

        # Condense middle turns into dense summary
        summary_lines = []
        for m in middle_turns:
            role = m.get("role", "msg").upper()
            content = (m.get("content") or "").strip()
            if content:
                summary_lines.append(f"• [{role}]: {content[:140]}...")

        condensed_text = (
            "### [Session Distillation / Compacted History]:\n"
            + "\n".join(summary_lines[:8])
            + f"\n(Compacted {len(middle_turns)} older turns to free memory)"
        )

        compacted_messages = [
            system_msg,
            {"role": "system", "content": condensed_text},
        ] + recent_turns

        freed_estimate = max(
            0, st["used_tokens"] - self.estimate_tokens(compacted_messages)
        )
        msg = f"🧹 Auto-Compacted session history (freed ~{freed_estimate:,} tokens)."
        return compacted_messages, True, msg


context_manager = ContextManager()
