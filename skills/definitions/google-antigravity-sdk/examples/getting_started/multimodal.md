# Multimodal Examples

This example demonstrates how to use multimodal inputs (images, documents) and
outputs (generating images) with the Google Antigravity SDK.

## Multimodal Input

You can pass images or documents directly to the `chat` method along with text.

### Basic Case: Text and Image

```python
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import Image

async with Agent(LocalAgentConfig()) as agent:
    # Load an image from a file
    image = Image.from_file("path/to/image.png")

    # Send both text and image in a list
    response = await agent.chat(["What is in this image?", image])
    print(await response.text())
```

### Advanced Case: Handling Documents

You can also pass other supported document types like PDFs.

```python
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import Document

async with Agent(LocalAgentConfig()) as agent:
    # Load a PDF document
    pdf = Document.from_file("path/to/document.pdf")

    # Ask the agent to summarize the document
    response = await agent.chat(["Summarize this document", pdf])
    print(await response.text())
```

## Multimodal Output

To enable the agent to generate images, you need to enable the `GENERATE_IMAGE`
tool.

### Generating Images

```python
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import CapabilitiesConfig, BuiltinTools

config = LocalAgentConfig(
    system_instructions=f"You have access to the '{BuiltinTools.GENERATE_IMAGE.value}' tool. Use it when asked to generate images.",
    capabilities=CapabilitiesConfig(
        enabled_tools=[BuiltinTools.GENERATE_IMAGE]
    ),
)

async with Agent(config) as agent:
    response = await agent.chat("Generate an image of a futuristic city.")
    print(await response.text())
```
