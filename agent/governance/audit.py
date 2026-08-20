"""
agent/governance/audit.py — Session Decision Log & Governance Audit Trail (/audit, /retro)
Records tool calls, governance hard-stop decisions, file modifications, and compiles retro reports.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from agent import __version__


class AuditRecord:
    def __init__(
        self,
        event_type: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        approved: Optional[bool] = None,
    ):
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.event_type = (
            event_type  # 'governance_hardstop', 'file_edit', 'tool_exec', 'lesson_learned'
        )
        self.description = description
        self.details = details or {}
        self.approved = approved

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "type": self.event_type,
            "description": self.description,
            "details": self.details,
            "approved": self.approved,
        }


class AuditManager:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.audit_dir = self.workspace_root / ".agnostic"
        self.audit_log: List[AuditRecord] = []

    def record(
        self,
        event_type: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        approved: Optional[bool] = None,
    ):
        self.audit_log.append(AuditRecord(event_type, description, details, approved))

    def generate_retro_markdown(self) -> str:
        """Generates an end-of-session retrospective markdown report."""
        if not self.audit_log:
            return "## 📋 Agnostic Session Audit & Retro\n\nNo governance events or modifications recorded this session."

        md = [
            "# 📋 Agnostic Session Retrospective & Governance Audit",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Events Tracked:** {len(self.audit_log)}\n",
            "## 🛡️ Governance Decisions & Hard-Stops",
        ]

        hardstops = [r for r in self.audit_log if r.event_type == "governance_hardstop"]
        if hardstops:
            for hs in hardstops:
                status = "✅ Approved" if hs.approved else "❌ Rejected"
                md.append(f"- **[{hs.timestamp}]** {hs.description} → `{status}`")
        else:
            md.append("- No safety hard-stops triggered this session.")

        md.append("\n## 📝 File Modifications & Side Effects")
        edits = [
            r for r in self.audit_log if r.event_type in ("file_edit", "file_write", "file_create")
        ]
        if edits:
            for e in edits:
                md.append(
                    f"- **[{e.timestamp}]** `{e.details.get('file', 'unknown')}` ({e.description})"
                )
        else:
            md.append("- No file changes recorded.")

        md.append("\n## ⚙️ Tool Execution Summary")
        tool_execs = [r for r in self.audit_log if r.event_type == "tool_exec"]
        md.append(f"- Total tool calls executed: **{len(tool_execs)}**")

        lessons = [r for r in self.audit_log if r.event_type == "lesson_learned"]
        if lessons:
            md.append("\n## 🧠 Rules & Lessons Promoted")
            for lesson in lessons:
                md.append(f"- **[{lesson.timestamp}]** {lesson.description}")

        md.append(f"\n---\n*Report compiled by Agnostic AI Harness v{__version__}*")
        return "\n".join(md)

    def export_audit_file(self) -> Path:
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.audit_dir / f"retro-{int(time.time())}.md"
        report_path.write_text(self.generate_retro_markdown(), encoding="utf-8")
        return report_path


audit_manager = AuditManager()
