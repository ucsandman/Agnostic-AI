"""
agent/workflows/diagram.py — Architecture & Flowchart Generator (/diagram, /map)
Scans project files, builds module dependencies, and generates clean Mermaid diagrams and architecture docs.
"""

import os
import re
from pathlib import Path
from typing import List, Set


class ArchitectureDiagrammer:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root

    def generate_mermaid_map(self) -> str:
        """Scan Python and JS imports to produce a visual Mermaid architecture diagram."""
        nodes: Set[str] = set()
        edges: List[str] = []

        for root, dirs, files in os.walk(self.workspace_root):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "venv", "__pycache__", "dist")
            ]
            for f in files:
                p = Path(root) / f
                if f.endswith((".py", ".js", ".cjs", ".ts")):
                    rel_source = p.relative_to(self.workspace_root).as_posix()
                    source_module = Path(rel_source).parent.as_posix() or "root"
                    nodes.add(source_module)

                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        # Python imports: from agent.tools import x
                        for match in re.finditer(r"(?:from|import)\s+([a-zA-Z0-9_.]+)", content):
                            imported = match.group(1).replace(".", "/")
                            target_module = (
                                Path(imported).parent.as_posix() if "/" in imported else imported
                            )
                            if (
                                target_module
                                and target_module != source_module
                                and (self.workspace_root / target_module).exists()
                            ):
                                edges.append(f'  "{source_module}" --> "{target_module}"')
                    except (SyntaxError, ValueError, OSError):  # unparseable file; skip its edges
                        pass

        # Deduplicate edges
        edges = sorted(list(set(edges)))[:25]

        mermaid = ["```mermaid", "graph TD"]
        for node in sorted(nodes):
            mermaid.append(f'  "{node}"["📁 {node}"]')
        for edge in edges:
            mermaid.append(edge)
        mermaid.append("```")
        return "\n".join(mermaid)
