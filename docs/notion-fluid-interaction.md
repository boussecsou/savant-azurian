# Notion: concise interaction and deletion approval

This change is proposed for the Hosted Agent. Local tests use simulated Notion,
model and Responses transports; they do not establish live Playground behavior.
The requested change to the original approval scope needs validation
against its acceptance criteria before that task can be closed.

## User experience

The English system messages ask Savant to act on the user's request, use the
user's language, be concise and avoid pre-announcing changes or exposing JSON,
tool schemas and internal classifier decisions in ordinary responses. They ask
the model to preserve information when improving presentation, and to let the
server request approval for deletions rather than asking twice. The internal
consent model is non-streaming and tagged `nostream`, so its structured verdict
does not appear as an assistant message in the LangGraph message stream.

## Execution policy

The existing server-side owner binding and official Notion endpoint requirement
remain. Recognized page/database/view/comment creation and page content
insertion can execute immediately. Known folder additions, page duplication and
restoration can also execute directly; removing folder files remains protected.
Scalar page property updates are allowed when
they do not clear values; list-valued replacements stay protected because their
previous members are unknown. Targeted content replacements execute automatically only
when the old visible words, symbols and literal links are retained; changing
layout while keeping the content is supported. Empty replacements, clearing
properties, full-page replacement, unknown commands and non-equivalent text
replacements remain protected. Unknown tools and generic Toolbox dispatch remain
behind approval; an explicitly configured `NOTION_WRITE_TOOL_NAMES` override
also remains protected. This conservatism can request approval for a harmless
rewrite; it cannot prove semantic equivalence or identify every possible
deletion. Dynamically discovered tool descriptions are not a security proof.

Automatic writes use the encrypted ledger to atomically claim the owner, thread,
turn and exact tool call before network I/O. Replaying the same checkpoint cannot
dispatch the same claimed call again. A timeout or error stops the tool loop and
requires inspecting the remote state before retrying. This is at-most-once
dispatch for the same recorded call, not exactly-once remote completion or
deduplication of a new user request with a new message/tool-call ID.

Protected operations retain the existing owner/thread binding, durable pending
action, schema fingerprint, expiration and one-use confirmation. Known Notion
page and database deletions show a compact count and links to the exact targets.
The `user_confirmed=true` flag required by Notion is bound to that operation in
the ledger, but the provider call is made only after the user confirms. Unknown
actions use a bounded complete disclosure fallback. An operation whose scope is
too large to present clearly is blocked and the user is asked to narrow it; a
short preview never authorizes unseen content. A mixed batch runs safe calls
first and stops on an error; protected actions wait for separate consent.

## Validation still required

Before treating this as done, review the updated policy and test the deployed version
with the owner's explicit authorization: a content-preserving layout edit and
an append without a confirmation, followed by a deletion refused without effect
and a separately approved deletion on a disposable page. Independently inspect
the resulting page and verify replay behavior. Test the real OAuth invalidation
and reconnection path separately. The hosted Playground can also display tool
trace events independently of assistant message text; hiding those events in
the product UI is outside this server-side text change.

References: [Notion MCP tools](https://developers.notion.com/guides/mcp/mcp-supported-tools),
[MCP annotations](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/).
