# Vulture whitelist for Agnostic Agent public APIs and framework overrides
from agent.tools.registry import ToolRegistry, ToolResult
from agent.governance.audit import AuditRecord
from agent.governance.context import ContextManager
from agent.tools.indexer import SymbolInfo
from agent.web.server import CompanionHandler

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
ToolRegistry
