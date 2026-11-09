# Outlook through the Foundry toolbox (task 28)

> **Status (2026-11-03): Outlook is set aside.** The agent now uses the toolbox `sa2-web` (web search and code interpreter only). In `sa2-toolbox`, the `outlook-sa2` source fails `tools/list` with `INVALID_CONFIGURATION` (MCP error `-32007`) when the BFF's managed identity is the caller, and one failing source makes the whole toolbox call fail. `sa2-toolbox` is left untouched for a later fix; the PWA hides the Outlook pill (`OUTLOOK_ENABLED = false` in `pwa/src/useOutlook.ts`).

The agent reads and sends mail from the owner's Outlook.com mailbox through a Foundry **toolbox**. Foundry runs the Outlook connector (a managed MCP server in the project's Connector Namespace), keeps the OAuth tokens and refreshes them; Savant holds no mail credential. Mail sent from Outlook reaches Gmail addresses like any other mail.

## What is deployed in Foundry

| Item | Value |
| --- | --- |
| Toolbox | `sa2-toolbox` (web search, code interpreter, Outlook) |
| Outlook connection | `outlook-sa2` (connector `outlook`, OAuth2, Italy North) |
| Agent setting | `TOOLBOX_ENDPOINT` in `azure.yaml`: the unversioned URL, so the toolbox's default version applies |
| Not used | `toolbox-lab-1`, whose `FoundryMCPServerpreview` can change Foundry itself |

Outlook operations exposed by the connection: `GetEmails`, `GetEmailsV2`, `GetEmail`, `GetAttachment`, `CalendarGetTable`, `ContactGetTable`, `MarkAsRead`, `Flag`, `Move`, `SendEmail`, `SendEmailV2`, `ReplyToV3`, `DeleteEmail`. There is **no draft operation** in the Outlook.com connector.

## Policy (`tools/toolbox_policy.py`)

The connector publishes no read-only hints, so calls are judged by name and unknown means protected.

| Call | Behaviour |
| --- | --- |
| Reads, attachments, calendar and contact metadata, mark as read, flag, move | Run directly |
| `tool_search`, web search, the sign-in tool | Run directly |
| **Send, reply, delete**, code interpreter, any unknown tool | Ask first: the server shows the exact message and waits for the owner's next message (semantic approval, one-shot ledger, bound to the exact arguments; fail closed) |

- With Foundry's **Tool search** enabled the model sees only `tool_search` and `call_tool`; the call is judged by the tool named in `call_tool`'s arguments. A malformed dispatch is protected. With Tool search off, tools are listed directly and judged the same way.
- The confirmation text is built from the exact arguments (To, Cc, Bcc, Subject, body up to 3000 characters, blockquoted). A send that cannot be shown in full (attachments, send-as, reply-to, oversized body, missing recipient) is refused rather than approved blind.
- Mail content is untrusted data. Instructions found in a mail or web page never count as approval.
- Replacing a toolbox version never widens the policy: a new operation is protected until it is added to `toolbox_policy.py`.

## Signing in

Consent is per identity and handled by Foundry. When the caller has not signed in, the connector answers a call with a sign-in link instead of data. The agent shows it, the owner signs in, then says "connected". The PWA pill reads this from the stream (the BFF flags the answer, never relays the link) and shows "Connect Outlook"; pressing it asks the agent for the link or a confirmation. The pill turns "Outlook connected" after the first successful Outlook call.

Local runs and the deployed agent are different callers, so each may need its own sign-in.

## PWA

Header pill with the Outlook mark, "Outlook" badge on tool steps (including operations behind `call_tool`: the BFF relays only the sanitised name of the dispatched tool), settings section listing what runs directly and what asks first. The interface is in English.

## Change the tools

1. Edit the connection's actions or the toolbox in the Foundry portal, publish the new toolbox version (`azd ai toolbox publish`).
2. If the operation is new, decide its class in `toolbox_policy.py` (read, reversible, or protected) and add a test.

## Revoke or roll back

- Clear `TOOLBOX_ENDPOINT` in `azure.yaml` and redeploy: the toolbox, its tools and the Outlook behaviour disappear.
- Cut mail access: delete the `outlook-sa2` connection in Foundry, and remove the app at account.live.com/consent/Manage.

## When the toolbox cannot be loaded

The toolbox is optional for the chat. If loading it fails for a request (for example the caller is not a signed-in user), the agent carries on with Notion and SSH, tells the model the toolbox is unavailable, and logs `toolbox_unavailable error_type=<type> status=<http status>`. Nothing else is logged. Foundry resolves the caller from the call id, so a request made by the BFF's managed identity is a different caller from a signed-in user (`azd ai agent invoke`).

## Known limits

- Preview features (Connector Namespace, Toolbox) without SLA.
- No drafts; no attachments in sent mail.
- An email containing words such as "authorization" or "bearer" in a send is blocked by the credential guard (`_safe_operation`): rephrase it.
- Delete asks for confirmation but shows only the end of the message id: the agent reads the mail first so the owner knows which one.
