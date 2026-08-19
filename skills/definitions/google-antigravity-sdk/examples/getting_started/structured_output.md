# Structured Output

This example demonstrates how to force the agent to produce structured data
(JSON) matching a specific schema. This is useful when you need the agent's
response to be machine-readable and conform to a strict structure.

## Code

```python
from google.antigravity import Agent, LocalAgentConfig
import pydantic

# Define the target schema using Pydantic
class ActionItem(pydantic.BaseModel):
    assignee: str
    task: str
    deadline: str

class MeetingSummary(pydantic.BaseModel):
    action_items: list[ActionItem]

# Configure the agent with the response schema
config = LocalAgentConfig(
    response_schema=MeetingSummary,
)

async with Agent(config) as agent:
    prompt = (
        "Extract action items from this text: Alice will update tests by "
        "Monday. Bob will run benchmarks tomorrow."
    )

    response = await agent.chat(prompt)

    # Access the structured output
    data = await response.structured_output()

    # The result is a dictionary matching the schema
    print(data)
```

## Key Concepts

-   **`response_schema`**: You can pass a Pydantic model to `LocalAgentConfig`
    via the `response_schema` parameter to enforce structured output.
-   **`response.structured_output()`**: This method retrieves the parsed JSON
    data matching the specified schema. It returns a dictionary (or `None` if
    parsing failed).
