# Web Tools Examples

This guide demonstrates how to enable and use built-in web search and URL
content reading tools with an agent.

## Enabling Web Search (`search_web`)

To use the web search tool, you must explicitly enable `SEARCH_WEB` in the
`CapabilitiesConfig` passed to `LocalAgentConfig`.

```python
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig, types

# Configure the agent to enable the SEARCH_WEB tool.
config = LocalAgentConfig(
    capabilities=CapabilitiesConfig(
        enabled_tools=[
            types.BuiltinTools.SEARCH_WEB,
        ]
    ),
)

async with Agent(config) as agent:
    response = await agent.chat("What is the current weather and temperature in New York City right now? Please provide the source.")
    print(await response.text())
```

> [!NOTE] When `SEARCH_WEB` is enabled, the agent can perform web searches to
> ground its responses with up-to-date information.

## Reading URL Content (`read_url_content`)

To fetch and extract page content directly from a URL, enable
`READ_URL_CONTENT`:

```python
# Configure the agent to enable URL content reading.
config = LocalAgentConfig(
    capabilities=CapabilitiesConfig(
        enabled_tools=[
            types.BuiltinTools.READ_URL_CONTENT,
            # Note: For massive web pages or lengthy documentation,
            # read_url_content caches the downloaded payload to disk.
            # Enabling VIEW_FILE allows the agent to inspect those files.
            types.BuiltinTools.VIEW_FILE,
        ]
    ),
)

async with Agent(config) as agent:
    target_url = "https://en.wikipedia.org/wiki/Google"
    prompt = f"Please read the full page content from {target_url} and tell me the exact date that Google acquired DeepMind Technologies."
    response = await agent.chat(prompt)
    print(await response.text())
```

> [!TIP] `read_url_content` scrapes static HTML pages into structured markdown
> chunks, allowing the model to analyze long web articles or documentation
> without manual copying. For large pages that exceed inline context thresholds,
> the payload is cached to disk; pairing `READ_URL_CONTENT` with `VIEW_FILE`
> ensures the agent can read those cached files.
