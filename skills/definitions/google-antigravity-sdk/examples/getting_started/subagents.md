# Subagents Example

This example demonstrates how an agent can spawn and delegate tasks to
sub-agents using the Google Antigravity SDK.

## Spawning a Subagent

To allow an agent to spawn subagents, you need to enable them in the
`CapabilitiesConfig`. By default, subagents are enabled.

Here is a minimal example of an agent spawning a subagent to perform a specific
task.

```python
from google.antigravity import Agent, LocalAgentConfig, types

# Enable subagents in the config
config = LocalAgentConfig(
    capabilities=types.CapabilitiesConfig(
        enable_subagents=True,
    )
)

async with Agent(config) as agent:
    # Prompt the agent to use a subagent
    response = await agent.chat("Use a subagent to write a short poem about nature.")
    print(await response.text())
```

## Consuming Subagent Output

The result from the subagent is typically delivered back to the main agent,
which then presents it or uses it. The `await response.text()` call will return
the final aggregated response, including the output produced by the subagent.

## Configuring Subagent Capabilities and Behavior

Subagents default to `agent_behavior=AgentBehavior.AUTONOMOUS`. You can declare
custom subagents and customize their capabilities and execution behavior via
`SubagentConfig` and `SubagentCapabilities`:

```python
from google.antigravity import Agent, LocalAgentConfig, types

config = LocalAgentConfig(
    subagents=[
        types.SubagentConfig(
            name="researcher",
            description="Researches topics autonomously.",
            capabilities=types.SubagentCapabilities(
                agent_behavior=types.AgentBehavior.AUTONOMOUS,
            ),
        ),
    ],
)
```
