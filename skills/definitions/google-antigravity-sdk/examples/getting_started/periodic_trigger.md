# Triggers and Periodic Checks

This example demonstrates how to use triggers in the Google Antigravity SDK.
Triggers are async functions that react to external events (like timers or file
changes) and can push messages to the agent.

## Code Example

```python
import logging
import asyncio
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.triggers import every, on_file_change, TriggerContext

# =============================================================================
# 1. Periodic Trigger (using `every` helper)
# =============================================================================
async def periodic_check(ctx: TriggerContext):
    """Periodic check that logs status."""
    logging.info("TRIGGER: Performing periodic health check.")
    # You can send messages to the agent:
    # await ctx.send("System status: OK")

# Create a trigger that runs every 60 seconds
timer_trigger = every(60, periodic_check)

# =============================================================================
# 2. File Change Trigger (using `on_file_change` helper)
# =============================================================================
async def handle_file_change(ctx: TriggerContext, changes):
    """Callback for file change events."""
    for change in changes:
        logging.info(f"TRIGGER: File {change.path} was {change.kind}")
    # await ctx.send("Configuration updated.")

# Create a trigger that watches a file or directory
# Note: Requires 'watchfiles' package to be installed.
file_trigger = on_file_change("/path/to/watch", handle_file_change)

# =============================================================================
# 3. Custom Trigger (any async function matching the signature)
# =============================================================================
async def custom_poll_trigger(ctx: TriggerContext):
    """Custom trigger that polls an external source."""
    logging.info("TRIGGER: Custom polling trigger started.")
    while True:
        # Simulate checking an external event
        event_detected = False # Replace with actual check

        if event_detected:
            await ctx.send("Custom event detected!")

        await asyncio.sleep(30) # Poll every 30 seconds

# =============================================================================
# Configuration and Execution
# =============================================================================
config = LocalAgentConfig(
    system_instructions="You are a helpful assistant.",
    triggers=[timer_trigger, file_trigger, custom_poll_trigger],
)

async with Agent(config) as agent:
    # The agent runs, and all triggers fire in the background.
    # Perform your agent interactions here.
    pass
```
