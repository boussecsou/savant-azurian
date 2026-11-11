# SPEC-002: Azure for Students constraints

- **Status:** Accepted
- **Date:** 2026-08-31 (verified on that date; check the official offer page before relying on it)
- **Related:** [ADR-0004](../adr/0004-reasoning-model-reference.md), [ADR-0005](../adr/0005-region-and-shared-speech-resource.md), [ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md)

## Why this document exists

The project was built on an **Azure for Students** subscription (offer `ms-azr-0170p`). Its limits shaped several decisions, and anyone reproducing the project on another subscription can ignore the ones that do not apply to them. This page records the constraints so those decisions make sense, and so the Azure for Students behaviour is not confused with the Starter offer.

## The offer

A verified university student account. One subscription per person. Not transferable.

## Funding and billing

- A credit of **US$100 for 12 months**, renewable while the person is still a student.
- No card at sign-up.
- Billing runs through Azure Sponsorships, with no active payment method and no way to add funds.
- The spending limit is on and equals the credit. It cannot be topped up.
- When the credit runs out or after 365 days, the subscription is **disabled**. The options then are to renew the student offer or to upgrade to Pay-As-You-Go.

## What is allowed

First-party Azure services, within the credit and the free tiers, and in the allowed regions: Speech, Foundry and Azure OpenAI (billed on the credit), Container Apps, Storage, Key Vault, AI Search, Cosmos DB, virtual machines and more.

## What is not covered

Support plans, Azure DevOps, paid Visual Studio, App Center, ExpressRoute, Marketplace and third-party offers, Entra ID Premium and separate licences.

## Project constraints that follow

- **Regions.** A policy limits deployment to a fixed list, so everything runs in Italy North ([ADR-0005](../adr/0005-region-and-shared-speech-resource.md)).
- **Model quota.** Some model SKUs show zero quota ([ADR-0004](../adr/0004-reasoning-model-reference.md)).
- **Front-end hosting.** Azure Static Web Apps is unavailable because it exists in none of the allowed regions, and a Marketplace plan is not an option ([ADR-0010](../adr/0010-monorepo-local-pwa-and-entra-owner-access.md)).
- **Cost discipline.** The deployment guide gives a [cost estimate](../deployment.md#what-it-costs) and `azd down --purge` to stop spending.

## Reference

The official offer page: <https://azure.microsoft.com/pricing/offers/ms-azr-0170p/>.
