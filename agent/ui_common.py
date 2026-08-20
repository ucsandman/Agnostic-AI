"""
agent/ui_common.py — Shared pieces for the two hand-maintained agent UIs (cli.py, tui.py).

Both cli.py (prompt_toolkit REPL) and tui.py (Textual app) need the same slash-command
table, @file/#symbol/@image prompt expansion, user-message formatting, safe-text rendering
for untrusted tool/model output, and CLI startup plumbing. This module is the single
definition of each so the two UIs cannot drift apart again.
"""

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from rich.text import Text

from agent import __version__
from agent.llm.detector import ModelDoctor
from agent.tools.indexer import code_indexer, CodebaseIndexer

# command -> the one-line help both UIs print. Iterating the dict yields the
# commands, so it doubles as the completion table (see docs/slash-commands.md —
# a test keeps the two in sync).
SLASH_COMMANDS = {
    "/theme": "[name] — terminal colour theme; picker when no name is given",
    "/plan": "<task> — ask the model for a step-by-step plan before touching code",
    "/fix": "[cmd] — run the tests (or read the last trace), diagnose, fix in one turn",
    "/compact": "[undo] — condense older turns into a summary; undo restores the last one",
    "/trust": "reads|tests|all — set the session trust tier",
    "/untrust": "back to the strict trust tier",
    "/session": "[save|load|list <name>] — no args opens the resume picker",
    "/audit": "write a Markdown report of the session and export it",
    "/retro": "alias of /audit",
    "/research": "<topic> — spawn a researcher subagent and return its notes",
    "/review": "spawn a reviewer subagent over git status / recent diffs",
    "/swarm": "<task> — three subagents in parallel, then a combined summary",
    "/diagram": "scan imports and print a Mermaid dependency diagram",
    "/map": "alias of /diagram",
    "/pr": "draft a pull-request title and body from the branch diff",
    "/harvest": "run engine/harvest/harvest.cjs over local agent logs",
    "/test": "[cmd] — loop fix-and-rerun until the tests pass or the retry cap",
    "/doctor": "probe the endpoint: model id, context length, latency",
    "/model": "[key|N] [sub-model] [effort] — interactive picker, or switch preset/model/effort",
    "/undo": "revert the last file write / edit",
    "/checkpoint": "save|restore|list [name] — named multi-file snapshots",
    "/commit": "propose a conventional commit from git status + diff",
    "/learn": "<lesson> — append a candidate rule for the distiller",
    "/schedule": 'every 30s "prompt" | list | stop <id>|all — background routines',
    "/loop": '<N> "prompt" — run a prompt N times in the background',
    "/state": "show the persistent whiteboard (.agnostic/state.md)",
    "/distill": "run the promotion ladder and pruner",
    "/web": "start the web companion on http://127.0.0.1:7843",
    "/clear": "clear the screen / output log, keep memory",
    "/multiline": "paste mode for long logs and specs (legacy CLI)",
    "/help": "this list",
    "/exit": "quit",
}


def help_text() -> str:
    """The /help body both UIs print, rendered from SLASH_COMMANDS — the two
    hand-written copies drifted from the table and from each other."""
    return "\n".join("  {:<12}{}".format(cmd, hint) for cmd, hint in SLASH_COMMANDS.items())


def complete_token(query: str, candidates, limit: int = 8) -> list:
    """Candidates for an @file / #symbol Tab completion: case-insensitive prefix
    matches first, then substring matches, capped at `limit`."""
    q = query.lower()
    prefix = [c for c in candidates if c.lower().startswith(q)]
    seen = set(prefix)
    substr = [c for c in candidates if q in c.lower() and c not in seen]
    return (prefix + substr)[:limit]


def stream_tail(chunks, max_lines: int = 12) -> str:
    """The live 'agent is typing' block: everything streamed so far, clipped to its
    last `max_lines` lines so the growing block cannot push the input box off screen.
    The full text is rendered into the log when the message finishes."""
    return "\n".join("".join(chunks).splitlines()[-max_lines:])


# The busy-indicator verb pool. One is picked per turn (not per tick) so the status
# bar reads as a label, not a slot machine. Override with AGNOSTIC_SPINNER_VERBS.
BUSY_VERBS: tuple[str, ...] = (
    "Percolating",
    "Noodling",
    "Untangling",
    "Wrangling",
    "Pondering",
    "Marinating",
    "Whirring",
    "Spelunking",
    "Rummaging",
    "Distilling",
    "Simmering",
    "Triangulating",
)


def busy_verbs(env: Optional[dict] = None) -> tuple[str, ...]:
    """The verb pool, with AGNOSTIC_SPINNER_VERBS (comma separated) as an override.
    An unset or all-blank override falls back to BUSY_VERBS — never an empty pool,
    which would make random.choice raise mid-turn."""
    raw = (env if env is not None else os.environ).get("AGNOSTIC_SPINNER_VERBS", "")
    verbs = tuple(v.strip() for v in raw.split(",") if v.strip())
    return verbs or BUSY_VERBS


def busy_indicator(elapsed_s: float, verb: str) -> str:
    """The live busy fragment: '∴ Percolating… 47s · esc to cancel'.

    Pure and monotonic-clock-agnostic — the caller passes an elapsed duration, so
    this never reads the wall clock and renders identically for the same inputs.
    """
    s = max(0, int(elapsed_s))
    clock = f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"
    return f"∴ {verb}… {clock} · esc to cancel"


def fold_summary(text: str, limit: int = 600) -> Tuple[str, int]:
    """(clipped, hidden_line_count) for a folded tool-output card.

    Clips at the last newline at or before `limit` so a card never ends mid-line,
    and reports how many lines the fold hid — a fold that cannot say what it ate
    is the Codex mistake. Returns (text, 0) when nothing is hidden.
    """
    if len(text) <= limit:
        return text, 0
    cut = text.rfind("\n", 0, limit)
    cut = limit if cut <= 0 else cut
    return text[:cut], text[cut:].count("\n") + 1


def _short(n: int) -> str:
    """Compact token counts for the status bar: '843' / '620k' / '2.0M'."""
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}k"
    return str(n)


def context_segment(st: dict, width: int = 10) -> Tuple[str, str]:
    """(text, rich_style) for the status bar. Fixed width so the bar never jitters.

    Thresholds match ContextManager.render_gauge: green <60, yellow <80, red above.
    render_gauge itself is deliberately left alone — it returns a 16-block Rich
    *markup* string keyed to a messages list, which a Text-based status bar cannot
    use. This takes the already-computed status dict, so there is no second
    estimate pass.
    """
    pct = float(st["percentage"])
    filled = min(width, int(pct / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    style = "green" if pct < 60 else "yellow" if pct < 80 else "red"
    # The percentage is right-aligned in a fixed 4-column field ('   5%' … ' 100%'):
    # left-aligned, every repaint would shift everything after it by a column.
    return (
        f"CTX {bar} {f'{pct:.0f}%'.rjust(4)} "
        f"({_short(st['used_tokens'])}/{_short(st['max_tokens'])})",
        style,
    )


def parse_slash_command(line: str) -> Tuple[str, str]:
    """Splits a slash-command line into (command, args) on the first whitespace token.

    e.g. '/test some [bracket] arg' -> ('test', 'some [bracket] arg').
    Using str.replace(cmd, "") to strip the command corrupts args that happen to repeat
    the command token elsewhere in the line — split on the first token instead.

    Returns ("", "") for a line that isn't a slash command at all, so callers can
    safely match on `cmd` without accidentally treating a plain prompt that happens
    to start with a command word (e.g. "fix this bug") as "/fix".
    """
    line = line.strip()
    if not line.startswith("/"):
        return "", ""
    parts = line.split(maxsplit=1)
    cmd = parts[0][1:]
    args = parts[1].strip() if len(parts) > 1 else ""
    return cmd, args


def safe_text(content: str, style: Optional[str] = None) -> Text:
    """Wraps raw/untrusted text (tool output, model text, subprocess output) for Rich
    display WITHOUT parsing it as console markup. A grep hit like '[/etc/hosts]' or a
    model emitting '[/]' must never reach Panel(str) or Text.from_markup(f"...{x}...") —
    both parse brackets as markup and raise rich.errors.MarkupError on malformed tags.
    """
    text = str(content)
    return Text(text, style=style) if style else Text(text)


class LineForwarder:
    """File-like stdout sink that forwards each COMPLETE line to `emit` as soon as
    it is written. Used by the TUI's background worker instead of io.StringIO —
    StringIO only handed its contents over once fn() returned, so /test, /fix and
    /swarm stayed silent for minutes. Call flush_remainder() when the redirect ends.
    """

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(s)

    def flush(self) -> None:
        """No-op: lines are emitted as they complete. Rich's Console calls this."""

    def flush_remainder(self) -> None:
        if self._buf:
            self._emit(self._buf)
            self._buf = ""


def history_file_path() -> Path:
    """The prompt history both UIs share (prompt_toolkit FileHistory format)."""
    return Path.home() / ".agnostic" / "agent_history.txt"


class PromptHistoryRing:
    """Up/down prompt history for the TUI input, persisted in the very file the
    legacy CLI's prompt_toolkit FileHistory uses — a '# <timestamp>' header per
    entry with each of its lines prefixed by '+' — so both shells share one history.

    `index == len(entries)` means "at the live line the user is typing".
    """

    CAP = 500

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else history_file_path()
        self.entries = self._load()
        self.index = len(self.entries)

    def _load(self):
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # no history file yet, or unreadable — start empty
            return []
        entries, current = [], []
        for line in raw.splitlines():
            if line.startswith("+"):
                current.append(line[1:])
            elif current:
                entries.append("\n".join(current))
                current = []
        if current:
            entries.append("\n".join(current))
        return [e for e in entries if e.strip()][-self.CAP :]

    def append(self, entry: str) -> None:
        if entry.strip() and (not self.entries or self.entries[-1] != entry):
            self.entries.append(entry)
            del self.entries[: -self.CAP]
            self._write(entry)
        self.index = len(self.entries)

    def _write(self, entry: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # newline="\n": prompt_toolkit's FileHistory writes raw LF bytes and keeps
            # whatever follows a '+' verbatim — a CRLF from Windows text mode would come
            # back as a trailing '\r' on every entry the legacy CLI reloads.
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n# {}\n".format(datetime.now().isoformat()))
                for line in entry.splitlines():
                    fh.write("+{}\n".format(line))
        except OSError:  # a read-only home must never break the prompt
            pass

    def prev(self) -> Optional[str]:
        """The next-older entry, or None when there is nothing older."""
        if self.index <= 0:
            return None
        self.index -= 1
        return self.entries[self.index]

    def next(self) -> Optional[str]:
        """The next-newer entry, "" back at the live line, None if already there."""
        if self.index >= len(self.entries):
            return None
        self.index += 1
        return self.entries[self.index] if self.index < len(self.entries) else ""


def parse_confirm_answer(answer: str) -> Tuple[bool, bool, str]:
    """Reads a y/n answer to a hard-stop confirmation. Returns (approved, unrecognized, reason).

    'y'/'yes' -> (True, False, ''); 'n'/'no' -> (False, False, ''). A verdict followed by
    whitespace or ':' carries the rest as a reason — 'n: too risky, patch the test instead'
    -> (False, False, 'too risky, patch the test instead') — which the caller feeds into the
    next turn. Anything else -> (False, True, '') and the CALLER MUST NOT treat that as an
    answer: a mistimed keystroke must never revoke a safety decision.
    """
    m = re.match(r"(y|yes|n|no)\b[\s:]*(.*)", answer.strip(), re.IGNORECASE | re.DOTALL)
    if not m:
        return False, True, ""
    return m.group(1).lower() in ("y", "yes"), False, m.group(2).strip()


def format_user_display(raw_input: str) -> str:
    """Formats user input for clean display in the user panel.

    Puts @image: references on their own lines and ensures text body is cleanly
    separated, matching Claude Code's prompt layout.
    """
    formatted = re.sub(r"[ \t]*(@image:\S+)[ \t]*", r"\n\1\n", raw_input)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted).strip()
    return formatted


def expand_prompt_references(user_prompt: str, indexer: CodebaseIndexer) -> str:
    """Injects code snippets and references for any @file, #symbol, or @image found in prompt."""
    image_refs = re.findall(r"@image:([a-zA-Z0-9_\-./\\]+)", user_prompt)
    file_refs = re.findall(r"@([a-zA-Z0-9_\-./\\]+)", user_prompt)
    symbol_refs = re.findall(r"#([a-zA-Z0-9_.:]+)", user_prompt)

    injected_context = []

    ws_root = getattr(indexer, "workspace_root", Path(os.getcwd()))
    if isinstance(ws_root, str):
        ws_root = Path(ws_root)

    for img_rel in image_refs:
        img_path = (ws_root / img_rel).resolve()
        if not img_path.exists():
            img_path = (Path(os.getcwd()) / img_rel).resolve()

        if img_path.exists() and img_path.is_file():
            try:
                from PIL import Image

                with Image.open(img_path) as im:
                    w, h = im.size
                    fmt = im.format
                size_kb = img_path.stat().st_size / 1024.0
                injected_context.append(
                    f"### [Attached Image Reference: @image:{img_rel} ({w}x{h} {fmt}, {size_kb:.1f} KB)]\n"
                    f"Image file on disk: `{str(img_path)}`"
                )
            except Exception:
                injected_context.append(
                    f"### [Attached Image Reference: @image:{img_rel}]\n"
                    f"Image file on disk: `{str(img_path)}`"
                )

    for f in file_refs:
        if f == "image" or f.startswith("image:"):
            continue
        # Routes through the guarded indexer — resolve_file itself refuses secret/
        # out-of-workspace paths (see agent/tools/indexer.py _check_access).
        res = indexer.resolve_file(f)
        if res:
            rel, content = res
            injected_context.append(f"### [Context Reference: @{rel}]:\n```\n{content[:2500]}\n```")

    for s in symbol_refs:
        res = indexer.resolve_symbol(s)
        if res:
            loc, snippet = res
            injected_context.append(f"### [Symbol Reference: #{s} ({loc})]:\n```\n{snippet}\n```")

    if injected_context:
        return user_prompt + "\n\n" + "\n\n".join(injected_context)
    return user_prompt


def build_arg_parser() -> argparse.ArgumentParser:
    """Shared argparse setup for both UI entrypoints."""
    parser = argparse.ArgumentParser(description="Agnostic AI Autonomous Coding Agent")
    parser.add_argument("--version", action="version", version=f"agnostic {__version__}")
    parser.add_argument(
        "--url",
        default="http://localhost:1234/v1",
        help="LLM API Base URL (LM Studio, Ollama, etc.)",
    )
    parser.add_argument("--model", default="local-model", help="Model name / ID")
    parser.add_argument("--api-key", default="lm-studio", help="API Key")
    parser.add_argument(
        "--compact",
        action="store_true",
        default=True,
        help="Use compact harness prompt for local context limits (default: True)",
    )
    parser.add_argument(
        "--full-prompt",
        action="store_true",
        help="Force loading full 14KB system prompt",
    )
    parser.add_argument("--prompt", "-p", help="Single prompt execution mode")
    parser.add_argument(
        "--ask-permissions",
        action="store_true",
        default=False,
        help="Prompt y/n for hard-stop commands (git push, rm -rf, deploys). Without this flag hard-stops are DENIED, not auto-approved.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the real-time visual web companion on port 7843 (next free port if taken)",
    )
    return parser


def detect_model(url: str, api_key: str, fallback_model: str):
    """Auto-discovers the active model from the endpoint.

    Returns (doctor, detected_model, detection).
    """
    doctor = ModelDoctor(base_url=url, api_key=api_key)
    detection = doctor.inspect()
    detected_model = detection.get("active_model") or fallback_model
    return doctor, detected_model, detection


def model_preset_rows(presets: dict, active_model: str, local_online: bool = False) -> list:
    """Builds the /model table: one (number, active, key, name, context, effort,
    availability) row per preset, in PRESETS order — so '/model <n>' can index it.

    Availability is probed locally only: env var for hosted APIs, the bridged CLI on
    PATH for subscription presets, the current doctor result for the local endpoint.
    """
    rows = []
    for i, (key, p) in enumerate(presets.items(), 1):
        provider = str(p.get("provider", "local"))
        if provider.endswith("-sub"):
            cli = str(p.get("base_url", "")).split("://")[-1] or key
            avail = f"{cli} CLI ready" if shutil.which(cli) else f"{cli} CLI not on PATH"
        elif provider == "local":
            avail = "endpoint online" if local_online else "endpoint offline"
        else:
            envs = [p.get("api_key_env")] + list(p.get("alt_api_key_envs") or [])
            found = next((e for e in envs if e and os.getenv(e)), None)
            avail = f"{found} set" if found else "set {}".format(p.get("api_key_env") or "API key")
        ctx = p.get("context_window") or 0
        rows.append(
            (
                str(i),
                "●" if p.get("model") == active_model else "",
                key,
                str(p.get("name", key)),
                "{}k".format(ctx // 1000) if ctx else "?",
                str(p.get("default_effort", "medium")),
                avail,
            )
        )
    return rows


EFFORT_LEVELS = ("low", "medium", "high")


def parse_model_args(
    tokens: list, presets: dict
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """'/model <key|N> [sub-model] [effort]' -> (preset_key, sub_model, effort, error).

    A 1-based number indexes PRESETS order (the /model table); an effort word is
    recognised anywhere after the key, everything else is the subscription's
    concrete model (e.g. '/model 2 claude-fable-5' or '/model 2 fable high').
    """
    if not tokens:
        return None, None, None, None
    key = tokens[0].lower()
    if key.isdigit():
        keys = list(presets)
        idx = int(key) - 1
        if not 0 <= idx < len(keys):
            return None, None, None, f"No preset #{key}. Type /model to list."
        key = keys[idx]
    sub_model = effort = None
    for tok in tokens[1:]:
        if tok.lower() in EFFORT_LEVELS:
            effort = tok.lower()
        else:
            sub_model = tok
    return key, sub_model, effort, None


def endpoint_status_line(detection: dict, model: str) -> Tuple[str, str]:
    """Honest two-state endpoint render shared by both UIs: (text, rich_style).

    An offline endpoint must never be reported as a working model — the default
    `--model local-model` is a placeholder, not a model that answered.
    """
    url = detection.get("base_url", "the configured endpoint")
    if detection.get("status") == "online":
        return f"✓ Connected to {url} (Model: {model})", "dim green"
    return (
        f"⚠️ Local endpoint offline at {url}\n"
        "   Next: /doctor to inspect it, /model <preset> to switch, or restart with --url <endpoint>",
        "dim yellow",
    )


def index_workspace() -> None:
    """Pre-indexes the workspace for fast fuzzy @file/#symbol autocomplete and lookups."""
    code_indexer.workspace_root = Path(os.getcwd()).resolve()
    code_indexer.index_workspace()


def maybe_start_web_companion(agent, open_browser: bool = True):
    """Starts the live visual web companion server. Returns (ok, web_url)."""
    from agent.web.server import start_companion_server, companion_telemetry

    companion_telemetry.bind_agent(agent)
    ok, web_url = start_companion_server(7843)
    # Only ok=True means a server is listening — web_url otherwise holds the startup
    # exception text, and opening a browser at the port anyway just shows a dead tab.
    if ok and open_browser:
        import webbrowser

        try:
            webbrowser.open(web_url)
        except (OSError, webbrowser.Error):  # no browser available; the URL is still reported
            pass
    return ok, web_url
