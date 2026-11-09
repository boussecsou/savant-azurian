/**
 * Parts of the interface that exist in the design but whose backend does not yet. They stay off
 * (like OUTLOOK_ENABLED) so the interface never promises what is not there.
 */

/** Documents per project (upload, real indexing states, sources under answers): Blob + Azure AI Search. */
export const DOCUMENTS_ENABLED = true;

/** Reports and charts beside the thread. Needs an artifact channel in the protocol. */
export const CANVAS_ENABLED = false;

/** Files added from the composer. They join the active project's documents (no per-message files). */
export const ATTACHMENTS_ENABLED = DOCUMENTS_ENABLED;
