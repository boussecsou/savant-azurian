# The Savant model: GPT-6 Luna

The migration of 8 October 2026 moved to the `gpt-6-luna` model: version `2026-09-22`, Global Standard, capacity 150. It is the default of the Bicep template (`MODEL_NAME`, `MODEL_VERSION`, `MODEL_SKU`, `MODEL_CAPACITY`, see the [configuration reference](configuration.md#azd-environment-inputs)). The history of the choice is in [ADR-0004](adr/0004-reasoning-model-reference.md) and [ADR-0006](adr/0006-model-fallback-and-change-control.md).

## Configuration and authentication

The deployment name is the value of `AZURE_AI_MODEL_DEPLOYMENT_NAME`. The CD passes the GitHub variable of the same name to the `azd` environment, then `azure.yaml` injects it into the new version of the Hosted Agent. Changing the variable alone does not change the versions already published. The pipeline keeps OIDC and its check of a green CI on the exact SHA of `main`.

For a local run, use the same values:

```env
AZURE_OPENAI_BASE_URL=https://<account>.openai.azure.com/openai/v1/
AZURE_AI_MODEL_DEPLOYMENT_NAME=<deployment-name>
```

The full URL `/openai/responses?api-version=2025-04-01-preview` shown in the portal is not a base URL for `ChatOpenAI`. The client uses the v1 path `/responses`, without an `api-version` parameter.

The bearer token keeps the scope `https://ai.azure.com/.default` and `DefaultAzureCredential`: the local developer account, or the Hosted Agent's managed identity in Azure. The agent's identity needs the `Cognitive Services OpenAI User` role on the account; that scope also covers a new deployment in the same resource. No additional role and no secret is needed.

## Responses and history

`build_model()` explicitly uses `use_responses_api=True` and `output_version="responses/v1"`. GPT-6 Luna limits function calling through Chat Completions to reasoning `none`; Responses keeps the default reasoning and the LangGraph tools.

The history stays managed by LangGraph. Model requests have `store=False` and ask for `reasoning.encrypted_content`, to replay the reasoning items after a tool or a checkpoint restore. The client does not use `previous_response_id` on the model side. The `previous_response_id` of the Hosted Agent's public protocol stays managed by the Responses server.

The tests go through the real OpenAI and LangChain clients with a simulated HTTP transport, synchronous and asynchronous: an answer, the `echo` tool, resuming the model and rereading a serialized history. The real validation uses the existing model, then the CD smoke test; it does not prove real access to Notion.

To go back to the previous model, set `AZURE_AI_MODEL_DEPLOYMENT_NAME` to the earlier deployment, then explicitly publish a new version with the existing pipeline. The workflow does no automatic rollback.

References: [Azure OpenAI Entra authentication](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/managed-identity), [GPT-6 Luna and function calling](https://developers.openai.com/api/docs/models/gpt-6-luna).
