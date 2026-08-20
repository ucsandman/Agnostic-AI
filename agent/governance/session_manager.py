"""
agent/governance/session_manager.py — Session Bookmarking, State Serialization & Restore
Allows saving/loading active conversation turns, context state, and whiteboard between sessions.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


class SessionManager:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.sessions_dir = self.workspace_root / ".agnostic" / "sessions"

    def save_session(
        self,
        name: str,
        history: List[Dict[str, Any]],
        state_notes: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Saves current conversation history and state into a named session snapshot."""
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
            session_file = self.sessions_dir / f"{clean_name}.json"

            data = {
                "name": clean_name,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "turn_count": len(history),
                "history": history,
                "notes": state_notes or "",
            }

            session_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return (
                True,
                f"Session successfully saved as '{clean_name}' ({len(history)} turns).",
            )
        except Exception as e:
            return False, f"Failed to save session: {str(e)}"

    def load_session(self, name: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
        """Loads conversation history from a named session snapshot."""
        clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
        session_file = self.sessions_dir / f"{clean_name}.json"

        if not session_file.exists():
            # Try without sanitization or search
            matching = list(self.sessions_dir.glob(f"*{name}*.json"))
            if matching:
                session_file = matching[0]
            else:
                return (
                    None,
                    f"Session '{name}' not found. Use '/session list' to view available sessions.",
                )

        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            history = data.get("history", [])
            return (
                history,
                f"Loaded session '{session_file.stem}' ({len(history)} turns restored, saved on {data.get('saved_at')}).",
            )
        except Exception as e:
            return None, f"Failed to load session '{name}': {str(e)}"

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Returns metadata for all saved sessions."""
        if not self.sessions_dir.exists():
            return []

        results = []
        for file in sorted(self.sessions_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                results.append(
                    {
                        "name": file.stem,
                        "saved_at": data.get("saved_at", "Unknown"),
                        "turn_count": data.get("turn_count", len(data.get("history", []))),
                        "notes": data.get("notes", ""),
                    }
                )
            except (OSError, json.JSONDecodeError):  # a corrupt session file is skipped, not fatal
                pass
        return results

    def delete_session(self, name: str) -> Tuple[bool, str]:
        clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
        session_file = self.sessions_dir / f"{clean_name}.json"
        if session_file.exists():
            session_file.unlink()
            return True, f"Session '{clean_name}' deleted."
        return False, f"Session '{clean_name}' not found."


session_manager = SessionManager()
