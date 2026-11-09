# ADR-0013: The interface shows only what exists

- **Status:** Accepted
- **Date:** 2026-11-05
- **Tags:** infra

## Context

The interface prototype shows more than the backend can do: documents with indexing, a canvas of reports, attachments, an approval countdown, "always on" tools. A hard rule was set: the interface must never display an action, a connection or an approval as done if it did not happen.

## Decision

- Parts whose backend does not exist stay **off behind constants**: `DOCUMENTS_ENABLED` (needs retrieval), `CANVAS_ENABLED` (needs an artifact channel) and `ATTACHMENTS_ENABLED` (documents go through projects). The attach button is shown disabled, with a reason.
- Durations shown under a voice answer (speech-to-text, agent, text-to-speech) are **measured in the browser**. A part that was not measured is not shown.
- Web search and the VM read **"Managed by the agent"**, never "Connected" or "Always on", because the web client cannot verify them. Notion shows only the states the gateway reports, and there is no "Expired" state.
- The journal becomes **Settings, Diagnostics**. The roadmap cards of the old projects view are removed.
- All interface strings are in English. Spoken phrases stay French by default.

## Consequences

**Positive**

- Turning a feature on is a one-line change plus its component, when its backend lands.

**Negative / risks**

- The original definition of done for the documents task ("upload and list documents per project") is only partly met by the first interface phase: projects and sessions are there, documents wait for retrieval.

## Update

Documents were later enabled when retrieval and the upload pipeline landed. See [ADR-0021](0021-per-project-document-retrieval.md) and the [search documents guide](../search-documents.md).

## Related

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) (sections 8.2, 8.4, D9), [ADR-0012](0012-sessions-and-projects-behind-a-session-store.md)
