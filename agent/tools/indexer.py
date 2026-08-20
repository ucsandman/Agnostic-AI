"""
agent/tools/indexer.py — AST-Aware Repo Graph & Codebase Indexer (@file & #symbol resolution)
Parses Python and JS/TS files to extract exact class and function ranges, enabling zero-waste token slicing.
Supports .agentignore exclusion rules to preserve token context windows.
"""

import ast
import fnmatch
from functools import lru_cache
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set


DEFAULT_IGNORED_DIRS = {
    "node_modules",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    ".git",
    ".hg",
    ".svn",
    ".turbo",
    ".next",
    ".nuxt",
    "coverage",
    ".pytest_cache",
}

DEFAULT_IGNORED_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".lock",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".min.js",
    ".min.css",
    ".map",
    ".wasm",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".gif",
    ".svg",
}


@lru_cache(maxsize=8)
def _guard_for_root(workspace_root: str):
    """One SafetyGuard per workspace root — building it re-reads guards.json and
    recompiles every policy regex, which is far too expensive to redo per path check."""
    from agent.governance.guard import SafetyGuard

    return SafetyGuard(workspace_root=workspace_root)


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
        self.symbol_type = symbol_type  # 'class', 'function', 'method', 'symbol'
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
        # Reverse index: which symbol names a file contributed. Without it,
        # purging one changed file walks every symbol in the workspace.
        self._symbols_by_file: Dict[Path, List[str]] = {}
        self._sorted_symbols: Optional[List[str]] = None
        self.indexed_files: List[str] = []
        self._file_mtimes: Dict[str, tuple] = {}
        self._ignore_patterns: Set[str] = set()
        self._load_agentignore()

    def _load_agentignore(self):
        """Loads custom patterns from .agentignore if present in workspace root."""
        self._ignore_patterns = set()
        ignore_file = self.workspace_root / ".agentignore"
        if ignore_file.exists():
            try:
                for line in ignore_file.read_text(encoding="utf-8").splitlines():
                    clean = line.strip()
                    if clean and not clean.startswith("#"):
                        self._ignore_patterns.add(clean)
            except OSError:  # unreadable .agentignore; fall back to the default ignore set
                pass

    def is_ignored(self, path: Path) -> bool:
        """Determines if a path should be ignored by default or .agentignore rules."""
        try:
            rel_str = str(path.relative_to(self.workspace_root)).replace("\\", "/")
        except ValueError:
            rel_str = str(path).replace("\\", "/")

        # Check parent folder names
        for part in path.parts:
            if part in DEFAULT_IGNORED_DIRS or part.startswith("."):
                if part != ".agentignore":
                    return True

        # Check extensions
        if path.suffix.lower() in DEFAULT_IGNORED_EXTS:
            return True

        # Check explicit .agentignore glob patterns
        for pattern in self._ignore_patterns:
            if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True

        return False

    def index_workspace(self, force: bool = False):
        """Scan workspace and index Python and JavaScript/TypeScript symbols with mtime caching."""
        self._load_agentignore()
        current_files: List[str] = []

        found_files_set = set()

        for root, dirs, files in os.walk(self.workspace_root):
            # Prune ignored directories in-place
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in DEFAULT_IGNORED_DIRS
                and not any(fnmatch.fnmatch(d, p) for p in self._ignore_patterns)
            ]
            for f in files:
                p = Path(root) / f
                if self.is_ignored(p):
                    continue

                try:
                    rel_path = str(p.relative_to(self.workspace_root)).replace("\\", "/")
                    current_files.append(rel_path)
                    found_files_set.add(rel_path)
                except ValueError:
                    continue

                try:
                    stat = p.stat()
                    # Key on (mtime, size): a rewrite within the same mtime tick
                    # still changes size, so edits are never missed.
                    fingerprint = (stat.st_mtime, stat.st_size)
                except Exception:
                    fingerprint = (0.0, -1)

                if force or self._file_mtimes.get(rel_path) != fingerprint:
                    self._file_mtimes[rel_path] = fingerprint
                    is_py = f.endswith(".py")
                    is_js = f.endswith((".js", ".ts", ".jsx", ".tsx"))
                    if is_py or is_js:
                        # Symbol purging is O(#symbols); only code files hold any.
                        self._remove_symbols_for_file(p)
                        if is_py:
                            self._index_python_file(p)
                        else:
                            self._index_js_file(p)

        # Clean up deleted files
        deleted_files = set(self._file_mtimes.keys()) - found_files_set
        for del_f in deleted_files:
            del self._file_mtimes[del_f]
            self._remove_symbols_for_file(self.workspace_root / del_f)

        current_files.sort()
        self.indexed_files = current_files

    def _remove_symbols_for_file(self, file_path: Path):
        names = self._symbols_by_file.pop(file_path, None)
        if not names:
            return
        self._sorted_symbols = None
        for name in set(names):
            remaining = [sym for sym in self.symbols.get(name, []) if sym.file_path != file_path]
            if remaining:
                self.symbols[name] = remaining
            else:
                self.symbols.pop(name, None)

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
        except (OSError, SyntaxError, ValueError):  # unparseable source contributes no symbols
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
                        sym = SymbolInfo(name, "symbol", file_path, idx, min(len(lines), idx + 40))
                        self._add_symbol(name, sym)
        except (OSError, re.error):  # unreadable source contributes no symbols
            pass

    def _add_symbol(self, name: str, sym: SymbolInfo):
        self._sorted_symbols = None
        self.symbols.setdefault(name, []).append(sym)
        self._symbols_by_file.setdefault(sym.file_path, []).append(name)

    def get_indexed_files(self) -> List[str]:
        if not self.indexed_files:
            self.index_workspace()
        return self.indexed_files

    def get_all_symbols(self) -> List[str]:
        if not self.symbols:
            self.index_workspace()
        if self._sorted_symbols is None:
            self._sorted_symbols = sorted(self.symbols.keys())
        return self._sorted_symbols

    def resolve_symbol(self, symbol_name: str) -> Optional[Tuple[str, str]]:
        """Return (relative_file_path:start-end, extracted_code_snippet)."""
        clean_name = symbol_name.lstrip("#@").strip()
        matches = self.symbols.get(clean_name)
        if not matches:
            # Try lazy re-index if not found
            if not self.symbols:
                self.index_workspace()
                matches = self.symbols.get(clean_name)
            if not matches:
                return None

        sym = matches[0]
        try:
            lines = sym.file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            snippet = "\n".join(lines[sym.start_line - 1 : sym.end_line])
            rel_path = str(sym.file_path.relative_to(self.workspace_root)).replace("\\", "/")
            return (f"{rel_path}:{sym.start_line}-{sym.end_line}", snippet)
        except Exception:
            return None

    def _check_access(self, clean_path: str, target: Path) -> Optional[str]:
        """Returns a refusal reason if the path is a protected secret or outside the workspace."""
        # Guard is keyed on workspace_root because that is re-pointed at runtime.
        active_guard = _guard_for_root(str(self.workspace_root))
        for candidate in (clean_path, str(target)):
            safe, reason = active_guard.check_path_access(candidate)
            if not safe:
                return f"refused: secret path — {reason}"

        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return (
                f"refused: out-of-workspace path — '{clean_path}' resolves outside "
                f"the active workspace ({self.workspace_root})."
            )
        return None

    def resolve_file(self, file_path_str: str) -> Optional[Tuple[str, str]]:
        """Resolves an @file reference and returns (relative_path, content)."""
        clean_path = file_path_str.lstrip("@").strip()
        target = (self.workspace_root / clean_path).resolve()

        refusal = self._check_access(clean_path, target)
        if refusal:
            return (clean_path, refusal)

        if not target.exists() or not target.is_file():
            # Try matching against indexed files
            for idx_f in self.get_indexed_files():
                if idx_f.endswith(clean_path) or clean_path in idx_f:
                    target = (self.workspace_root / idx_f).resolve()
                    refusal = self._check_access(idx_f, target)
                    if refusal:
                        return (idx_f, refusal)
                    break

        if target.exists() and target.is_file():
            try:
                rel = str(target.relative_to(self.workspace_root)).replace("\\", "/")
                content = target.read_text(encoding="utf-8", errors="replace")
                return (rel, content)
            except Exception:
                return None
        return None


code_indexer = CodebaseIndexer()
