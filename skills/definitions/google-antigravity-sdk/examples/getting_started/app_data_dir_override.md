# Application Data Directory Override

This example demonstrates how to override the default application data directory
(`app_data_dir`) in `LocalAgentConfig` to control where the agent stores
generated artifacts (like `task.md`), scratch files, and media on disk.

## Overriding Artifact Storage

By default, the agent writes artifacts and scratch files to
`~/.gemini/antigravity/brain/`. You can customize this by providing a path.

> [!IMPORTANT] **The path must be an absolute path.** Passing relative paths or
> unexpanded tildes (`~/`) will trigger a validation error.

```python
import tempfile
from google.antigravity import Agent, LocalAgentConfig

# Create a custom directory for application data storage
custom_app_data = tempfile.mkdtemp()

config = LocalAgentConfig(
    app_data_dir=custom_app_data,
)

async with Agent(config) as agent:
    # Generated artifacts and scratch files will be saved inside custom_app_data
    await agent.chat("Create an artifact named 'notes.md' summarizing this conversation.")
```
