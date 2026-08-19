# Customizing Retry & Backoff Behavior

By default, the agent backend automatically enables retries for transient errors:

- **API Retries**: Defaults to 2 retries (3 total attempts) with a 1,000ms initial exponential backoff for transient network errors (such as HTTP 429 rate limits, 5xx server errors, or connection drops).
- **Model Output Retries**: Defaults to 4 retries when the model produces malformed tool calls or output that fails structured schema validation (e.g., violating a configured `response_schema`).

This example demonstrates how to use `RetryConfig` to **customize, override, or disable** this default retry behavior without writing custom retry loops in your application code.

## Code

```python
from google.antigravity import Agent, LocalAgentConfig, types

# 1. Specialized Intent Presets
# Use built-in classmethod presets when running specialized workloads:
benchmark_config = LocalAgentConfig(
    retry_config=types.RetryConfig.benchmark()  # Unbounded API retries for 429/503 quota resilience
)

# 2. Advanced Explicit Configuration
# Use explicit Pydantic models to fine-tune both API retries and model output validation retries.
explicit_config = LocalAgentConfig(
    retry_config=types.RetryConfig(
        api_retry=types.ModelAPIRetryConfig(
            max_retries=5,
            initial_sleep_duration_ms=1000,
            exponential_multiplier=2.0,
            jitter_range=0.1,
        ),
        model_output_retry=types.ModelOutputRetryConfig(
            max_retries=2,  # Tighten output validation retries from default of 4 down to 2
        ),
    )
)

async with Agent(explicit_config) as agent:
    # The agent will use your custom retry thresholds and backoff multipliers
    # instead of the system defaults.
    response = await agent.chat("Summarize our latest system architecture.")
    print(await response.text())
```

## Key Concepts

- **Default Resilience**: You do not need to configure `retry_config` for interactive chat; the backend automatically retries API errors and tool validation errors by default.
- **`RetryConfig.benchmark()`**: Unbounded preset designed for load tests and evaluation suites to survive transient 429/503 errors while inheriting production default model output retries.
- **`ModelAPIRetryConfig`**: Customizes network and API-level retries with exponential backoff and jitter. Ideal for high-flake environments or strict fail-fast requirements (`max_retries=0`).
- **`ModelOutputRetryConfig`**: Customizes how many times the backend prompts the model to correct malformed tool calls or schema validation mismatches before raising an error.
