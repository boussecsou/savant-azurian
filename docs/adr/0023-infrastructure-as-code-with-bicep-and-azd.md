# ADR-0023: Describe the Azure infrastructure in Bicep and deploy it with the Azure Developer CLI

- **Status:** Proposed
- **Date:** 2026-11-09
- **Tags:** infra, azure

## Context

Every Azure resource of the project was created by hand in the portal, which was the right way to learn the services. It does not make the project reproducible: a newcomer cannot stand up their own copy, the repository held personal values in its deployment file, and nothing records the resources, their settings or their role assignments.

## Decision drivers

- A newcomer can reproduce the setup without editing personal values.
- One source of configuration, with secrets only in Key Vault.
- Native to the tools the project already uses (`azd`, Foundry hosted agents).
- Reviewable in a pull request.

## Considered options

| Option | Notes |
| --- | --- |
| Bicep with `azd` | Native to Azure and to the Foundry extension, no state file to manage. **Chosen** |
| Terraform | Capable, but adds a state backend and a second tool for a project that is Azure-only |
| Portal steps in a document | Not reproducible and not reviewable |
| Foundry extension provisioning only (`deployments[]`) | Covers the project and model, not the registry, Container Apps, Cosmos DB, Search or role assignments |

## Decision

- Describe the resources in **Bicep modules** under `infra/`, one module per concern, deployed by `azd provision`.
- Every personal value comes from the **Azure Developer CLI environment**, which Bicep outputs also fill. `azure.yaml` only references `${VAR}`.
- Role assignments are part of the template, including the Cosmos DB data-plane role.
- What Bicep cannot do well stays in **small, dry-run-by-default scripts**: secrets that must be generated into Key Vault, the roles of the hosted agent's identity (which exists only after its first deployment), and GitHub variables. The search index has its own script, the hosted agent is deployed by `azd deploy`, and the Easy Auth app registration stays a documented portal step.
- GitHub Actions authenticates with a **user-assigned identity and a federated credential** created by the template, so there is no app registration to create by hand for CI.

## Consequences

**Positive**

- One command provisions a copy of the project, and `azd down` removes it.
- Roles and settings are reviewed like code.

**Negative / risks**

- **Not yet validated against a real subscription.** The status of this ADR changes to Accepted when a clean deployment has been done. Several points need checking first: how `azd` combines an `infra:` block with the Foundry project service, what a hosted agent needs beyond an account and a project, and the model's availability in the chosen region. They are listed in the [deployment guide](../deployment.md#what-to-verify-first).
- The first deployment is a validation, so it should start with `azd provision --preview`.

## Related

[ADR-0020](0020-keyless-access-with-entra-and-key-vault.md), [ADR-0005](0005-region-and-shared-speech-resource.md), [deployment guide](../deployment.md), [configuration reference](../configuration.md)
