# Google Antigravity SDK Architecture

This document provides a high-level overview of the core concepts in the Google
Antigravity SDK.

The SDK is built on three pillars: **Agent**, **Conversation**, and
**Connection**.

## Core Concepts

### Agent

The `Agent` is the entry point for creating and managing AI workflows. It
provides a high-level API that abstracts away the complexity of environment
setup, tool loading, and connection management. - **Responsibilities**: Handles
configuration (models, capabilities, tools, policies), manages session
lifecycle, and orchestrates hooks and triggers.

### Conversation

The `Conversation` object represents a stateful session, managing the history
and context of an interaction. - **Responsibilities**: Accumulates step history,
tracks turns, manages context compaction, and provides streaming methods like
`chat()`. It ensures context is maintained across multiple turns.

### Connection

The `Connection` is an abstract interface handling transport to the agent
backend. - **Responsibilities**: Sends prompts and receives execution steps. It
decouples higher-level APIs from specific transport details or backend locations
(local, cloud, etc.).

The SDK ships multiple `ConnectionStrategy` implementations for different
backends:

-   `LocalConnectionStrategy`: Connects to the remote Gemini API.
-   `LiteRTConnectionStrategy`: Runs models locally on-device using LiteRT-LM.
-   `LocalOpenAIConnectionStrategy`: Connects to any OpenAI-compatible local
    server (Ollama, LM Studio, etc.).

For details on local model configuration, see `references/local_models.md`.

## Relationship and Flow

The core concepts work together in a hierarchical fashion to manage an
interaction:

1.  **Configuration**: The user defines the desired behavior and capabilities in
    an `AgentConfig`.
2.  **Orchestration**: An `Agent` is instantiated with this configuration. When
    the agent session starts, it uses the configuration to determine the
    appropriate connection strategy and creates a `Conversation`.
3.  **State & History**: The `Conversation` object represents the active
    session. It establishes the low-level `Connection` to the backend and acts
    as the central hub for maintaining message history and managing the
    turn-by-turn flow of the interaction.
4.  **Communication**: When you send a message (e.g., via `agent.chat()`), the
    `Conversation` uses the underlying `Connection` to transmit data to the
    backend and stream the response back.

This structure allows the user to interact with a simple, high-level `Agent`
interface while the `Conversation` and `Connection` handle the state management
and transport details under the hood.
