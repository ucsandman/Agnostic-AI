# Filesystem-Based Skill Loading

This example demonstrates how to load domain-specific knowledge from directories
containing `SKILL.md` files with YAML frontmatter, following the
[official Agent Skills specification](https://agentskills.io/home).

An **Agent Skill** is a standardized way to give AI agents new capabilities and
expertise. It typically consists of a directory containing a `SKILL.md` file
with instructions and metadata, and optionally scripts, references, and assets.
Skills allow capturing domain expertise and repeatable workflows for reuse
across different agents.

## Loading Skills

You can configure an agent to load skills from the filesystem by specifying the
`skills_paths` parameter in `LocalAgentConfig`.

In a typical scenario, a user might ask the agent to use a specific skill and
provide a path to it. The agent can then be configured to load that skill.

> [!IMPORTANT] The `skills_paths` parameter accepts a list of paths. Each path in the list can be:
> - A directory that *contains* skill folders (each containing a `SKILL.md` file). The agent will discover all skills in that directory.
> - A direct path to a specific skill folder (containing a `SKILL.md` file) to load just that skill.

```python
from google.antigravity import Agent, LocalAgentConfig

# Path to the PARENT directory containing skill folders
skills_directory = "/path/to/skills"

config = LocalAgentConfig(
    skills_paths=[skills_directory]
)

async with Agent(config) as agent:
    response = await agent.chat("Please list your available skills and tell me what they do.")
    print(await response.text())
```
