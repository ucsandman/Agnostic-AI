# Vulture whitelist for Agnostic Agent public APIs and framework overrides
from agent.tools.registry import ToolRegistry, ToolResult
from agent.governance.audit import AuditRecord
from agent.governance.context import ContextManager
from agent.tools.indexer import SymbolInfo
from agent.web.server import CompanionHandler, CompanionTelemetry, _CompanionServer
from agent.tools.diff_viewer import TaskManager, task_manager
from agent.cli import (
    AgnosticCompleter,
    _handle_alt_v,
    _handle_enter,
    _handle_ctrl_enter,
)
from agent.governance.interceptor import CodeInterceptor
from agent.governance.undo import ThemeManager, UndoManager
from agent.governance.session_manager import SessionManager
from agent.governance.state import StateManager
from agent.governance.watchdog import SandboxWatchdog
from agent.governance.learn import learner
from agent.tools.mcp_discovery import MCPAutoDiscovery
from agent.tools.subagent import SubagentManager
from agent.workflows.planner import ExecutionPlan
from agent.workflows.pr_pilot import PRAutoPilot
from agent.workflows.scheduler import TaskScheduler
from agent import ui_common

# Whitelist methods
AuditRecord.to_dict
ContextManager.set_max_tokens
ContextManager.auto_compact
SymbolInfo.to_dict
ToolResult.to_dict
ToolRegistry.get_openai_tools
ToolRegistry.execute
CompanionHandler.do_GET
CompanionHandler.log_message
CompanionTelemetry.set_diff
CompanionTelemetry.get_active_file
ToolRegistry

AgnosticCompleter.get_completions
_handle_alt_v
_handle_enter
_handle_ctrl_enter
learner.corrections_file
CodeInterceptor.run_quick_lint
ThemeManager.format_badge
UndoManager.get_history_summary
SessionManager.delete_session
StateManager.update_whiteboard
SandboxWatchdog.get_clean_snapshot_hash
SandboxWatchdog.rollback_to_clean
MCPAutoDiscovery.discover_mcp_servers
SubagentManager.spawn_parallel
ExecutionPlan.add_step
ExecutionPlan.update_status
ExecutionPlan.record_deviation
ExecutionPlan.render_markdown
PRAutoPilot.create_feature_branch
TaskScheduler.cancel_all
# socketserver reads this class attribute; vulture cannot see that.
_CompanionServer.daemon_threads
# Background-task API kept for the TUI/web companion; not wired to a slash command yet.
TaskManager.list_tasks
TaskManager.send_input
TaskManager.kill_task
TaskManager.schedule
task_manager

# Shared UI entry points: cli.py and tui.py use these, but the pre-commit
# vulture pass sees only the staged files, so it calls them dead otherwise.
ui_common.SLASH_COMMANDS
ui_common.parse_slash_command
ui_common.safe_text
ui_common.format_user_display
ui_common.build_arg_parser
ui_common.detect_model
ui_common.maybe_start_web_companion
