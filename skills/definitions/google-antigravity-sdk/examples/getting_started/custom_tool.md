# Custom Tool Example

This example demonstrates how to equip an agent with a custom Python function as
a tool.

## Defining and Using a Custom Tool

To create a custom tool, define a Python function with a clear docstring. The
agent uses the docstring to understand what the tool does and when to use it.

```python
from google.antigravity import Agent, LocalAgentConfig

# 1. Define the tool with a descriptive docstring
def get_current_temperature(location: str) -> str:
    """Gets the current temperature for a given location.

    Args:
        location: The city and state, e.g. "San Francisco, CA".
    """
    # In a real application, this would call an external weather API.
    # For this example, we return a hardcoded string.
    return f"The temperature in {location} is 72°F."

# 2. Configure the agent with the custom tool
config = LocalAgentConfig(
    tools=[get_current_temperature],
)

# 3. Chat with the agent
async with Agent(config) as agent:
    response = await agent.chat("What's the temperature in Mountain View?")

    # Stream the response
    async for chunk in response:
        print(chunk, end="", flush=True)
```

## Maintaining State with ToolContext

To maintain state across multiple turns in a conversation, you can use
`ToolContext`. The `ToolContext` is automatically injected into your tool
function if you include it in the arguments.

```python
from google.antigravity import Agent, LocalAgentConfig, ToolContext

# 1. Define the tool that uses ToolContext to maintain state
def record_fruit(fruit_name: str, count: int, ctx: ToolContext) -> str:
    """Records the mention of fruits and updates the total count.

    Args:
        fruit_name: The name of the fruit.
        count: The number of fruits mentioned.
        ctx: The tool context (injected).
    """
    # Retrieve current state or initialize if not present
    current_counts = ctx.get_state("fruit_counts", {})

    # Update state
    current_counts[fruit_name] = current_counts.get(fruit_name, 0) + count
    ctx.set_state("fruit_counts", current_counts)

    total = current_counts[fruit_name]
    return f"Recorded {count} {fruit_name}(s). Total {fruit_name} count is now {total}."

# 2. Configure the agent with the stateful tool
config = LocalAgentConfig(
    tools=[record_fruit],
    system_instructions=(
        "You are a fruit inventory assistant. Use the record_fruit tool to "
        "record fruits mentioned by the user."
    ),
)

# 3. Chat with the agent across multiple turns
async with Agent(config) as agent:
    # Turn 1
    print("User: I have 5 apples.")
    response1 = await agent.chat("I have 5 apples.")
    print("Agent: ", end="")
    async for chunk in response1:
        print(chunk, end="", flush=True)
    print()

    # Turn 2
    print("User: I just got 3 more apples.")
    response2 = await agent.chat("I just got 3 more apples.")
    print("Agent: ", end="")
    async for chunk in response2:
        print(chunk, end="", flush=True)
    print()
```

## Overriding Built-in Tools

You can override any built-in tool (e.g., `view_file`, `run_command`) by
registering a custom tool with the **exact same name** as the built-in tool.

When you register a custom tool with a conflicting name, the SDK will
automatically prioritize your custom implementation. You do not need to
explicitly disable the built-in tool in the `disabled_tools` configuration.

The local harness will log an info message confirming the override: `Custom tool
"view_file" successfully overrides built-in tool.`

Example:

```python
def view_file(AbsolutePath: str) -> str:
    """Custom implementation of view_file."""
    return f"[Custom View] {AbsolutePath}"

config = LocalAgentConfig(
    tools=[view_file], # Overrides built-in view_file
)
```
