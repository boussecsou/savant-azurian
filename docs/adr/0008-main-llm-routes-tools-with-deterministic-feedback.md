# ADR-0008: Let the main model route tools, and emit deterministic live feedback

- **Status:** Accepted
- **Date:** 2026-09-02
- **Tags:** voice, agent

## Context

Savant must tell a simple conversational request from one that needs an external action. A tool-dependent request can take several seconds, and waiting in silence through the whole agent and tool loop makes a poor voice interaction.

A separate routing model would add one more model call to every utterance, including trivial greetings, and would add latency and architectural complexity.

## Decision

Use the **main language model as the semantic router.**

The model receives the final transcript, the conversation context, the system instructions and the tool definitions exposed through LangChain tool calling. It returns either a normal answer or a structured tool call. LangGraph does not classify intent itself: it reads the structured output and routes the execution.

When a tool call that will take noticeable time is detected, the runtime emits a short **deterministic acknowledgement** mapped to the tool, and starts the tool with minimal extra delay. For example, a Notion search yields "I'm looking in Notion." No second model call is needed to produce it.

## Consequences

**Positive**

- One semantic decision covers both direct replies and tool selection.
- Feedback is fast and predictable.

**Negative / risks**

- Tool definitions must reach the model before inference. The model does not first search for a list of tools.
- LangChain provides the model and tool abstractions, while LangGraph owns state, routing, execution, feedback, retries, timings and the final response.
- Fixed phrases can sound repetitive. Context-sensitive acknowledgements may be evaluated later, only if they add no material latency.

## Evolution

- The fixed announcements are now played by the web client itself from a table of phrases, without calling the model.
- A faster first model call without tools now answers tool-free turns and hands over to the full agent when a tool is needed (the `MODEL_FAST_PATH` setting). The main model is still the one that decides whether tools are needed.

## Related

[SDD-003](../design/sdd-003-conversational-voice-runtime.md), [ADR-0006](0006-model-fallback-and-change-control.md), [ADR-0007](0007-live-stt-with-utterance-final-trigger.md), [ADR-0022](0022-bounded-tool-execution.md)
