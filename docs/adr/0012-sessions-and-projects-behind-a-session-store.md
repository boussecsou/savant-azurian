# ADR-0012: Keep sessions and projects behind a `SessionStore` interface

- **Status:** Accepted
- **Date:** 2026-11-05
- **Tags:** infra, rag

## Context

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) turns the single conversation of the web client into **sessions** filed in **projects**. Cosmos DB is the eventual source of truth, and retrieval per project comes after it, but the interface has to exist and be usable before either.

## Decision

- The interface only knows a **`SessionStore`** interface (`loadWorkspace`, `saveWorkspace`, `loadMessages`, `saveMessages`, `deleteSession`). The first implementation uses `localStorage`; the Cosmos DB implementation goes through the backend without touching a component.
- The **workspace** (projects, session metadata, interface choices) is one record. **Messages** are stored per session, as text only: role, final text, channel (`voice`), date. Never tool arguments or results, which stay in the backend, and never timings.
- Every rule lives in a **pure reducer** with injected clock and ids, tested without a DOM: the default project cannot be deleted, an empty session is reused, the first user message titles the session, a turn is bound to the session it started in, and deletion is undoable.
- The legacy single conversation is **migrated once** into a session of the default project. The old key is removed only after the new data has been written.
- `conversation_id` (Foundry's last response ID) becomes a field **of the session**, so each session continues its own thread.
- Until the agent receives a project identifier, a project is **a local filing system**. The help text says "Projects group your sessions on this device" and never promises isolated memory.

## Consequences

**Positive**

- Moving to Cosmos DB changes one implementation, not the components.

**Negative / risks**

- Until the Cosmos DB store is connected, sessions exist on one device only, with no sync and no offline merge.
- Storage failures (blocked or full) never throw: the app works, it just does not remember.
- The undo window of a few seconds keeps a deleted session's messages in storage. Closing the tab inside that window leaves them orphaned, which is harmless and small.
- A `messageCount` field was added to the session, to know whether it is empty and to show the count without loading messages.

## Update

The Cosmos DB store is now implemented behind the backend (projects, sessions, messages) and the web client keeps a local store that it synchronizes with it. See the [workspace documentation](../workspace-cosmos.md).

## Related

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) (D1, D2, D6, D10), [ADR-0010](0010-monorepo-local-pwa-and-entra-owner-access.md)
