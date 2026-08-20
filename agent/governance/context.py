"""
agent/governance/context.py — Context Window Estimator, Meter & Smart Auto-Compaction
Calculates approximate token usage across messages and handles graceful manual (/compact) and background compaction.
"""

import json
from typing import List, Dict, Any, Tuple


class ContextManager:
    def __init__(
        self, max_context_tokens: int = 2000000, compaction_threshold: float = 0.75
    ):
        self.max_context_tokens = max_context_tokens
        self.compaction_threshold = compaction_threshold

    def set_max_tokens(self, max_tokens: int):
        self.max_context_tokens = max(1024, max_tokens)

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

    def compact_messages(
        self, messages: List[Dict[str, Any]], force: bool = False
    ) -> Tuple[List[Dict[str, Any]], bool, str]:
        """Compacts older turns into a dense summary."""
        st = self.get_status(messages)
        if not force and (not st["near_limit"] or len(messages) <= 4):
            return messages, False, "Context usage is well within limits."

        if len(messages) <= 3:
            return messages, False, "Conversation is too short to compact."

        system_msg = (
            messages[0]
            if messages and messages[0]["role"] == "system"
            else {"role": "system", "content": "You are an autonomous AI coding agent."}
        )
        # Retain last 3 turns verbatim, but never begin the retained window on an
        # orphaned 'tool' message — its assistant 'tool_calls' must come with it or
        # the next API call 400s.
        cut = len(messages) - 3
        while cut > 1 and messages[cut].get("role") == "tool":
            cut -= 1

        recent_turns = messages[cut:]
        middle_turns = messages[1:cut]
        if not middle_turns:
            return messages, False, "Conversation is too short to compact."

        # Condense middle turns into dense structured distillation
        summary_lines = []
        files_touched = set()
        test_findings = []

        for m in middle_turns:
            role = m.get("role", "msg").upper()
            content = (m.get("content") or "").strip()
            if not content:
                continue

            # Extract any touched file paths
            import re

            found_paths = re.findall(
                r'[\'"]?([a-zA-Z0-9_\-\.\/\\]+\.(?:py|ts|tsx|js|json|md|yaml|yml|html|css))[\'"]?',
                content,
            )
            for p in found_paths:
                if not p.startswith(".git") and not p.startswith(".secrets"):
                    files_touched.add(p)

            # Note test failures or passes
            if "FAILED" in content or "PASSED" in content or "pytest" in content:
                for line in content.splitlines():
                    if any(
                        kw in line for kw in ("PASSED", "FAILED", "ERROR", "assert")
                    ):
                        test_findings.append(line.strip()[:100])

            summary_lines.append(f"• [{role}]: {content[:160]}...")

        condensed_sections = ["### [Session Distillation / Compacted History]:"]
        if files_touched:
            condensed_sections.append(
                f"**Referenced / Modified Files:** {', '.join(sorted(list(files_touched))[:12])}"
            )
        if test_findings:
            condensed_sections.append(
                "**Key Test/Execution Findings:**\n"
                + "\n".join(f"  - {tf}" for tf in test_findings[:5])
            )

        condensed_sections.append(
            "**Chronological Dialogue Digest:**\n" + "\n".join(summary_lines[:12])
        )
        condensed_sections.append(
            f"(Compacted {len(middle_turns)} older turns to free context window)"
        )

        condensed_text = "\n\n".join(condensed_sections)

        # Combine leading system message with the session distillation so system message is strictly at index 0
        merged_system_content = (
            f"{system_msg.get('content', '')}\n\n{condensed_text}".strip()
        )
        compacted_messages = [
            {"role": "system", "content": merged_system_content}
        ] + recent_turns

        freed_estimate = max(
            0, st["used_tokens"] - self.estimate_tokens(compacted_messages)
        )
        msg = f"🧹 Compacted {len(middle_turns)} turns (freed ~{freed_estimate:,} tokens)."
        return compacted_messages, True, msg

    def auto_compact(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], bool, str]:
        return self.compact_messages(messages, force=False)


context_manager = ContextManager()  # noqa: vulture
