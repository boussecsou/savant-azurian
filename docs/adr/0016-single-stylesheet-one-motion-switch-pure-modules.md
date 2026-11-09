# ADR-0016: One stylesheet from the interface prototype, one motion switch, logic in pure modules

- **Status:** Accepted
- **Date:** 2026-11-05
- **Tags:** infra

## Context

The new interface is a port of an interface prototype. The web client has no UI library and no animation library, and its tests run in Node without a DOM.

## Decision

- The prototype's CSS (the same tokens as the web client plus a few new ones) **replaces** the old stylesheet. The Markdown and code-block rules are kept, and the components use the prototype's class names.
- **No new dependency.** Motion is CSS transitions with strong curves, under 300 ms, using `transform` and `opacity` only. Keyboard-initiated surfaces (the command palette and the `/` menu) do not animate.
- **Reduced motion has one source**: a `data-motion="reduce"` attribute on `<html>`, set from the operating-system preference or the owner's setting (System or On). The old media-query block is gone so the two cannot diverge.
- Everything that does not need a DOM goes into **pure modules** tested with Vitest: the workspace reducer, storage and migration, grouping, ID extraction, orb palettes and maths, palette filter, composer keys, approval hint, connection views, caption words and motion preference.
- Folding the side panels is done in steps (fade, then layout, then a FLIP transform on the orb) so that layout is never animated.
- The prototype's own scaffolding (its lab panel, scripted agent, simulated voice and fake report) is **not** ported.

## Consequences

**Positive**

- A small dependency surface and a large part of the logic covered by fast unit tests.

**Negative / risks**

- Components are verified by a Playwright pass against the development server with the backend mocked, not by Vitest. Safari, Firefox, screen readers and real phones are untested.
- Orb performance on a mid-range phone is not measured.

## Related

[SDD-005](../design/sdd-005-product-model-memory-and-interface.md) (section 8), [ADR-0010](0010-monorepo-local-pwa-and-entra-owner-access.md), [ADR-0013](0013-interface-shows-only-what-exists.md)
