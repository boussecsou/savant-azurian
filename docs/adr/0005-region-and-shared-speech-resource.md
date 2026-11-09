# ADR-0005: Deploy everything in Italy North with one shared Speech resource

- **Status:** Accepted
- **Date:** 2026-08-18
- **Tags:** azure, infra

## Context

An Azure for Students subscription carries a region policy that cannot be removed ([SPEC-002](../design/spec-002-azure-for-students-constraints.md)). The `Allowed resource deployment regions` policy limits it to `switzerlandnorth`, `polandcentral`, `spaincentral`, `norwayeast` and `italynorth`. Sweden Central, West Europe and France Central are denied.

Speech-to-text, text-to-speech, Foundry, Container Apps and Key Vault must stay in one allowed region. Within the allowed regions:

- Azure Speech Fast Transcription ([ADR-0002](0002-speech-fast-transcription-for-stt.md)) is not available in `norwayeast` or `switzerlandnorth`;
- `spaincentral` does not support Speech at all;
- `italynorth` is the only one offering Fast Transcription, Speech and the target reasoning model.

## Decision

- **Region:** Italy North (`italynorth`).
- **One Speech resource** (S0) serves both transcription and neural HD voices.
- The Foundry project, Key Vault, Container Apps, AI Search and Cosmos DB live in one resource group in that region.
- Use the Global Standard SKU for the model when a regional SKU is missing.

**If creating the Foundry project in Italy North fails**, the next candidate is `norwayeast`, and [ADR-0002](0002-speech-fast-transcription-for-stt.md) must be reopened (batch transcription instead of Fast Transcription).

## Consequences

**Positive**

- A single region keeps latency, networking and the bill simple, and Fast Transcription stays possible without changing ADR-0002.

**Negative / risks**

- The subscription policy is the hard constraint, and it also rules out Azure Static Web Apps (see [ADR-0010](0010-monorepo-local-pwa-and-entra-owner-access.md)).
- Anyone reproducing this project on another subscription is free to pick a different region, as long as the model, Speech and hosted agents are available there. The region is an input of the deployment (`AZURE_LOCATION` in the [configuration reference](../configuration.md)).

## Related

[ADR-0002](0002-speech-fast-transcription-for-stt.md), [ADR-0003](0003-azure-neural-hd-voices-for-tts.md), [ADR-0004](0004-reasoning-model-reference.md), [SDD-002](../design/sdd-002-architecture-and-azure-infrastructure.md)
