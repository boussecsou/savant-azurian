/** The documents an answer used, as the BFF relays them (id and file name only). No imports: shared by api.ts and documents.ts. */

/** A document an answer used, as the BFF relays it: id and file name only. */
export interface Source {
  documentId: string;
  title: string;
}

/** The sources of a turn, in order, each document once (several searches can cite the same one). */
export function mergeSources(current: readonly Source[] | undefined, added: readonly Source[]): Source[] {
  const merged = [...(current ?? [])];
  for (const source of added) {
    if (!merged.some((known) => known.documentId === source.documentId)) merged.push(source);
  }
  return merged;
}

/** Keeps only well-formed sources from a stream event. */
export function parseSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const { documentId, title } = item as Record<string, unknown>;
    return typeof documentId === "string" && documentId && typeof title === "string" && title.trim()
      ? [{ documentId, title: title.slice(0, 120) }]
      : [];
  });
}
