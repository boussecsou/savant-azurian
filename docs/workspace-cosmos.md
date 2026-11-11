# Projects and sessions in Cosmos DB

The backend keeps the owner's projects, sessions and messages in Cosmos DB for NoSQL ([SDD-005](design/sdd-005-product-model-memory-and-interface.md), phase 2). Without `COSMOS_ENDPOINT` nothing changes: there are no `/api/projects` or `/api/sessions` routes, and chat works as before.

## Resources

Created by the Bicep template ([deployment guide](deployment.md)), or by hand in the portal:

- A Cosmos DB account (Serverless, account keys disabled: Entra ID only).
- Database `sa2`; containers `projects` (`/id`), `sessions` (`/id`) and `messages` (`/sessionId`). The partition key cannot change after creation.
- The data role **Cosmos DB Built-in Data Contributor** (`00000000-0000-0000-0000-000000000002`) for the backend's managed identity. Cosmos data roles are not granted in "Access control (IAM)": use `az cosmosdb sql role assignment create`, or a `sqlRoleAssignments` resource in Bicep.
- The agent does not access Cosmos (reading sessions from the agent would come with session memory, which is not implemented).

## Backend configuration

| Variable | Role |
| --- | --- |
| `COSMOS_ENDPOINT` | The account's HTTPS origin, `*.documents.azure.com`. Turns the feature on. |
| `COSMOS_DATABASE` | Database name (default `sa2`). |

## Rules (`workspace.py`)

Everything belongs to a project. `Main` always exists and can be neither renamed nor deleted. Project names are unique (case-insensitive). A session belongs to one project and can move to another. Deleting a project or a session deletes what it contains. Only the text is kept, never the arguments or results of tools.

## Chat with a session

`POST /api/chat` and `/api/chat/stream` accept `session_id`. The backend then reads the session, sends `metadata.project_id` to the agent (never chosen by the model), continues the thread from the session's last `conversationId` if the browser gives none, and records the turn (question and answer) once the answer is finished. A storage failure is logged (`session_persist_failed`, without content) and never interrupts the answer.

## Routes (owner only, Easy Auth)

`GET/POST /api/projects`, `PATCH/DELETE /api/projects/{id}`, `GET/POST /api/sessions?project=`, `PATCH/DELETE /api/sessions/{id}`, `GET /api/sessions/{id}/messages`. Errors: 404 unknown, 409 conflict or the `Main` project, 422 invalid data, 502 storage unavailable.

## Deployment

The `azure-cosmos` dependency was added: merging redeploys the agent (once) and publishes the backend image. Updating the Container App stays manual: new image, the `COSMOS_ENDPOINT` variable (and `COSMOS_DATABASE` if different), then `/readiness`.
