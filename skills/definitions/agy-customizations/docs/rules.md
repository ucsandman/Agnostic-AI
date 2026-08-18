# Workspace Rules

Rules are guidelines and constraints that the agent must follow when operating
within specific directories. They are useful for enforcing coding styles, API
usage restrictions, or safety protocols.

## Rule Locations

The system automatically discovers and applies rules from the following
locations:

*   **Directory-Based Rules (`GEMINI.md` / `AGENTS.md`)**: Placed directly in
    any directory. The system walks up from the current working directory to the
    repository root and loads these files. They apply to the directory they
    reside in and all its subdirectories.

## Rule Format

Rules are written in Markdown. Standalone `GEMINI.md` / `AGENTS.md` files do not
support frontmatter and are always active for their directory scope.

## Rule Merging and Deduplication

*   Rules are automatically deduplicated. Even if a rule is discovered via
    multiple paths (e.g., inherited from parent directories), it is only applied
    once per conversation.
*   If a rule is defined in a plugin, it is loaded when the plugin is enabled.
