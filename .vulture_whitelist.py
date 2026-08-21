# Vulture whitelist: public APIs and framework callbacks the global pre-commit
# hook's vulture pass (staged files only, min confidence 60) cannot see being
# used. Every entry is a false positive, not a pardon for dead code — when a
# symbol here really dies, delete it from the code and from this file.
from agent import ui_common
from agent.cli import AgnosticCompleter, _handle_alt_v, _handle_enter, _handle_ctrl_enter
from agent.governance.audit import AuditRecord
from agent.governance.context import ContextManager
from agent.governance.interceptor import CodeInterceptor
from agent.governance.learn import learner
from agent.governance.session_manager import SessionManager
from agent.governance.state import StateManager
from agent.governance.undo import ThemeManager, UndoManager
from agent.governance.watchdog import SandboxWatchdog, watchdog
from agent.loop import AgentLoop
from agent.tools.indexer import SymbolInfo
from agent.tools.registry import ToolRegistry, ToolResult
from agent.tools.subagent import SubagentManager, SubagentWorker
from agent.governance.memory import MemoryStore
from agent.tui import AgnosticTUI
from agent.tui_composer import PromptArea
from agent.tui_model_picker import ModelPickerScreen
from agent.tui_memory import MemoryPickerScreen
from agent.tui_picker import PickerScreen
from agent.tui_diff import DiffPickerScreen
from agent.tui_rewind import RewindScreen
from agent.tui_sessions import SessionPickerScreen
from textual.widgets import OptionList
from agent.web.server import CompanionHandler, CompanionTelemetry, _CompanionServer
from agent.workflows.pr_pilot import PRAutoPilot
from agent.workflows.scheduler import TaskScheduler

# Serialisers and public methods called from the other UI / the web companion.
AuditRecord.to_dict
SymbolInfo.to_dict
ToolResult.to_dict
ToolRegistry.get_openai_tools
ToolRegistry.execute
ContextManager.set_max_tokens
ContextManager.auto_compact
CodeInterceptor.run_quick_lint
ThemeManager.format_badge
UndoManager.get_history_summary
UndoManager.changed_since
SessionManager.delete_session
StateManager.update_whiteboard
# Called from agent/tools/registry.py — dead only when that file is not staged.
StateManager.read_memory
StateManager.write_memory
SandboxWatchdog.get_clean_snapshot_hash
SandboxWatchdog.rollback_to_clean
watchdog
learner.corrections_file
SubagentManager.spawn_parallel
PRAutoPilot.create_feature_branch
TaskScheduler.cancel_all

# prompt_toolkit key-binding handlers (registered by decorator, called by the framework).
AgnosticCompleter.get_completions
_handle_alt_v
_handle_enter
_handle_ctrl_enter

# Textual App/Widget overrides and BINDINGS actions — invoked by the framework by name.
AgnosticTUI.CSS
AgnosticTUI.compose
AgnosticTUI.on_print
AgnosticTUI.action_cancel_turn
AgnosticTUI.action_clear_output
AgnosticTUI.action_history_prev
AgnosticTUI.action_history_next
AgnosticTUI.action_complete_slash
AgnosticTUI.action_quit_safe
AgnosticTUI.action_cycle_trust
AgnosticTUI.action_expand_output
AgnosticTUI.on_app_blur
AgnosticTUI.on_app_focus
AgnosticTUI.on_input_submitted
AgnosticTUI.on_text_area_changed
AgnosticTUI.on_mount
# The composer: Textual calls _on_key, tui.py reads/writes the Input-shaped shims.
PromptArea._on_key
PromptArea.value
PromptArea.cursor_position
AgnosticTUI.display

# http.server / socketserver read these class attributes and method names.
CompanionHandler.do_GET
CompanionHandler.do_POST
CompanionHandler.log_message
CompanionTelemetry.set_diff
CompanionTelemetry.get_active_file
_CompanionServer.daemon_threads

# Shared UI entry points: cli.py and tui.py use these, but the staged-files-only
# vulture pass calls them dead when only ui_common.py is staged.
ui_common.SLASH_COMMANDS
# tui.py assigns it; loop.py/registry read it — dead only when loop.py is not staged.
AgentLoop.confirm_callback
ui_common.parse_slash_command
ui_common.safe_text
ui_common.format_user_display
ui_common.build_arg_parser
ui_common.detect_model
ui_common.maybe_start_web_companion
ui_common.help_text
ui_common.complete_token
ui_common.stream_tail
ui_common.LineForwarder
ui_common.LineForwarder.flush  # file-like protocol: Rich Console calls it
# Textual framework hooks on the picker screens: DEFAULT_CSS, message handlers
# and action_* methods are invoked by Textual, never by our code.
PickerScreen.DEFAULT_CSS
PickerScreen.action_pick
PickerScreen.action_back
DiffPickerScreen.on_option_list_option_selected
MemoryPickerScreen.on_option_list_option_selected
ModelPickerScreen.on_option_list_option_selected
RewindScreen.on_option_list_option_selected
SessionPickerScreen.on_option_list_option_selected
OptionList.highlighted
# test stubs in tests/test_loop_client.py: read by the code under test, not the test
AgentLoop.turn_lock
SubagentWorker.build_registry
# Called from cli.py/tui*.py — dead only when those files are not staged.
LLMConfig.sub_models  # noqa: F821
LLMConfig.display_model  # noqa: F821
LLMClient.switch_model  # noqa: F821
AgentLoop.is_busy
AgentLoop.run_turn
# pytest autouse fixtures in tests/conftest.py, test_bridge.py, test_mcp.py, test_usage.py
_current_event_loop  # noqa: F821
_forget_codex_help  # noqa: F821
isolated_home  # noqa: F821
no_user_pricing  # noqa: F821
# Used by loop.py / tui phase — dead only when those callers are not staged.

MemoryStore
MemoryStore.save
MemoryStore.delete
MemoryStore.index_text
MemoryStore.recall
MemoryStore.get
MemoryStore.list
ui_common.MEMORY_USAGE
# Callers live in files not staged alongside these (staged-scope vulture pass).
SafetyGuard.get_trust_tier  # noqa: F821
PRAutoPilot.generate_pr_summary
AutoTestRunner.quick_fix  # noqa: F821
AutoTestRunner.auto_repair_loop  # noqa: F821
parse_tool_args  # noqa: F821
cost_usd  # noqa: F821
selection  # noqa: F821
# PickerScreen subclasses override the class attr; Textual reads it, not our code.
DiffPickerScreen.FOOTER_KEYS  # noqa: F821
MemoryPickerScreen.FOOTER_KEYS  # noqa: F821
