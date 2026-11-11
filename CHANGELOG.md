# Changelog

All notable changes are listed here. The file is maintained by [release-please](https://github.com/googleapis/release-please) from the [Conventional Commits](https://www.conventionalcommits.org/) history, and the format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0](https://github.com/boussecsou/savant-azurian/compare/v0.1.0...v0.2.0) (2026-11-11)


### Features

* **config:** document every setting and keep the docs in step with the code ([f175a22](https://github.com/boussecsou/savant-azurian/commit/f175a222a1e958fd08bdc28f75a3032cc0d0b058))
* **infra:** describe every Azure resource in Bicep and deploy it with azd ([300851c](https://github.com/boussecsou/savant-azurian/commit/300851c16f8d402c41b81d5a360cbc36f0ea2239))
* **web:** add a mock backend so the client runs with no Azure resource ([ae9bf43](https://github.com/boussecsou/savant-azurian/commit/ae9bf431366fc2a9fab847a160f7d692aa72e9af))

## 0.1.0

First public version.

### Added

- A hosted agent built on LangGraph, with Notion, SSH, web search and per-project document retrieval, behind two independent authorization layers.
- A FastAPI backend for the Notion OAuth callback and the owner-only web API, on Azure Container Apps.
- A React web client with a voice interface, projects and sessions.
- Infrastructure as code for the Azure resources (Bicep) and setup scripts that keep secrets in Key Vault.
- A complete configuration reference, and a design record of specifications, design documents and decision records.
