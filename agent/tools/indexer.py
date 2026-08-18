"""
agent/tools/indexer.py — AST-Aware Repo Graph & Codebase Indexer (@symbol resolution)
Parses Python and JS/TS files to extract exact class and function ranges, enabling zero-waste token slicing.
"""

import ast
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


class SymbolInfo:
    def __init__(
        self,
        name: str,
        symbol_type: str,
        file_path: Path,
        start_line: int,
        end_line: int,
        docstring: Optional[str] = None,
    ):
        self.name = name
        self.symbol_type = symbol_type  # 'class', 'function', 'method'
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.docstring = docstring

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.symbol_type,
            "file": str(self.file_path),
            "lines": f"{self.start_line}-{self.end_line}",
        }


class CodebaseIndexer:
    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or ".").resolve()
        self.symbols: Dict[str, List[SymbolInfo]] = {}

    def index_workspace(self):
        """Scan workspace and index Python and JavaScript/TypeScript symbols."""
        self.symbols.clear()
        for root, dirs, files in os.walk(self.workspace_root):
            # Ignore hidden and vendor directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "venv", "__pycache__", "dist", "build")
            ]
            for f in files:
                p = Path(root) / f
                if f.endswith(".py"):
                    self._index_python_file(p)
                elif f.endswith((".js", ".ts", ".jsx", ".tsx")):
                    self._index_js_file(p)

    def _index_python_file(self, file_path: Path):
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    sym = SymbolInfo(
                        node.name,
                        "class",
                        file_path,
                        node.lineno,
                        getattr(node, "end_lineno", node.lineno),
                    )
                    self._add_symbol(node.name, sym)
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_sym = SymbolInfo(
                                f"{node.name}.{item.name}",
                                "method",
                                file_path,
                                item.lineno,
                                getattr(item, "end_lineno", item.lineno),
                            )
                            self._add_symbol(f"{node.name}.{item.name}", method_sym)
                            self._add_symbol(item.name, method_sym)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sym = SymbolInfo(
                        node.name,
                        "function",
                        file_path,
                        node.lineno,
                        getattr(node, "end_lineno", node.lineno),
                    )
                    self._add_symbol(node.name, sym)
        except Exception:
            pass

    def _index_js_file(self, file_path: Path):
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for idx, line in enumerate(lines, 1):
                fn_match = re.search(
                    r"(?:function|class|const|let|var)\s+([A-Za-z0-9_$]+)\s*=?\s*(?:function|\(.*?\)\s*=>|class)?",
                    line,
                )
                if fn_match:
                    name = fn_match.group(1)
                    if name and not name.startswith("_"):
                        sym = SymbolInfo(
                            name, "symbol", file_path, idx, min(len(lines), idx + 40)
                        )
                        self._add_symbol(name, sym)
        except Exception:
            pass

    def _add_symbol(self, name: str, sym: SymbolInfo):
        if name not in self.symbols:
            self.symbols[name] = []
        self.symbols[name].append(sym)

    def resolve_symbol(self, symbol_name: str) -> Optional[Tuple[str, str]]:
        """Return (relative_file_path, extracted_code_snippet)."""
        clean_name = symbol_name.lstrip("@").strip()
        matches = self.symbols.get(clean_name)
        if not matches:
            return None

        sym = matches[0]
        try:
            lines = sym.file_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            snippet = "\n".join(lines[sym.start_line - 1 : sym.end_line])
            rel_path = sym.file_path.relative_to(self.workspace_root)
            return (f"{rel_path}:{sym.start_line}-{sym.end_line}", snippet)
        except Exception:
            return None


code_indexer = CodebaseIndexer()  # noqa: vulture
