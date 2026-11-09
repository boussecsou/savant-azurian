import { afterEach, describe, expect, it, vi } from "vitest";
import { streamEventFromForTest } from "./api";
import {
  DocumentApiError,
  MAX_DOCUMENT_BYTES,
  checkFile,
  deleteDocument,
  documentErrorMessage,
  documentFileUrl,
  documentKind,
  downloadDocument,
  formatSize,
  KIND_LABEL,
  listDocuments,
  settledUploads,
  uploadDocument,
  type ProjectDocument,
} from "./documents";
import { mergeSources, parseSources } from "./sources";

afterEach(() => vi.unstubAllGlobals());

const doc = (id: string, state: ProjectDocument["state"]): ProjectDocument => ({ id, projectId: "main", name: `${id}.pdf`, size: 1, uploadedAt: 0, state });

describe("files added in this page", () => {
  it("reports a file once it is indexed or has failed, and drops it from the watch", () => {
    const watched = new Map([["a", "a.pdf"], ["b", "b.pdf"], ["c", "c.pdf"]]);
    const outcomes = settledUploads(watched, [doc("a", "indexing"), doc("b", "ready"), doc("c", "failed")]);
    expect(outcomes).toEqual([
      { id: "b", name: "b.pdf", outcome: "ready" },
      { id: "c", name: "c.pdf", outcome: "failed" },
    ]);
  });

  it("forgets a file that left the list (removed meanwhile) without announcing anything", () => {
    expect(settledUploads(new Map([["a", "a.pdf"]]), [doc("z", "ready")])).toEqual([{ id: "a", name: "a.pdf", outcome: "gone" }]);
  });

  it("keeps watching what is still being sent or indexed", () => {
    expect(settledUploads(new Map([["a", "a.pdf"]]), [doc("a", "uploading")])).toEqual([]);
  });
});

describe("files", () => {
  it("accepts the indexed types up to 16 MB and says why otherwise", () => {
    expect(checkFile({ name: "SDD-003.PDF", size: 10 })).toBeNull();
    expect(checkFile({ name: "notes.md", size: 1 })).toBeNull();
    expect(checkFile({ name: "photo.png", size: 10 })).toMatch(/not supported/);
    expect(checkFile({ name: "empty.txt", size: 0 })).toMatch(/empty/);
    expect(checkFile({ name: "big.pdf", size: MAX_DOCUMENT_BYTES + 1 })).toMatch(/16 MB/);
  });

  it("names the kind for the badge and formats sizes", () => {
    expect([documentKind("a.pdf"), documentKind("b.DOCX"), documentKind("c.pptx"), documentKind("d.md"), documentKind("e.txt")]).toEqual(["pdf", "word", "slides", "markdown", "text"]);
    // The badge tells the real extension: a Markdown note is not a "TXT".
    expect([documentKind("d.md"), documentKind("e.txt")].map((kind) => KIND_LABEL[kind])).toEqual(["MD", "TXT"]);
    expect([formatSize(512), formatSize(2048), formatSize(3 * 1024 * 1024)]).toEqual(["512 B", "2 KB", "3.0 MB"]);
    expect(documentFileUrl("main", "a b")).toBe("/api/projects/main/documents/a%20b/file");
  });
});

describe("sources", () => {
  it("keeps well-formed sources, each document once and in order", () => {
    const parsed = parseSources([{ documentId: "d1", title: "plan.pdf" }, { documentId: "", title: "x" }, "junk", { documentId: "d2", title: " " }]);
    expect(parsed).toEqual([{ documentId: "d1", title: "plan.pdf" }]);
    expect(mergeSources(parsed, [{ documentId: "d1", title: "plan.pdf" }, { documentId: "d3", title: "notes.md" }]).map((s) => s.documentId)).toEqual(["d1", "d3"]);
  });

  it("reads the BFF's sources event", () => {
    expect(streamEventFromForTest({ type: "sources", id: "c1", sources: [{ documentId: "d1", title: "plan.pdf" }] })).toEqual({
      type: "sources", id: "c1", sources: [{ documentId: "d1", title: "plan.pdf" }],
    });
    expect(streamEventFromForTest({ type: "sources", id: "c1", sources: [] })).toBeNull();
  });
});

describe("requests", () => {
  it("sends the raw file with its name in the query, lists and deletes in the project", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      if (init.method === "POST") return new Response(JSON.stringify({ id: "d1", projectId: "p 1", name: "été.pdf", size: 3, uploadedAt: 1, state: "indexing" }), { status: 201 });
      if (init.method === "DELETE") return new Response("{}", { status: 200 });
      return new Response(JSON.stringify([{ id: "d1", projectId: "p 1", name: "été.pdf", size: 3, uploadedAt: 1, state: "ready" }, { bad: true }]));
    }));
    const file = Object.assign(new Blob(["abc"]), { name: "été.pdf" });
    expect((await uploadDocument("p 1", file)).state).toBe("indexing");
    expect(calls[0].url).toBe("/api/projects/p%201/documents?name=%C3%A9t%C3%A9.pdf");
    expect(calls[0].init.body).toBe(file);
    expect((await listDocuments("p 1")).map((d) => d.state)).toEqual(["ready"]);
    await deleteDocument("p 1", "d1");
    expect(calls[2]).toMatchObject({ url: "/api/projects/p%201/documents/d1", init: { method: "DELETE" } });
  });

  it("downloads a document's bytes with its name, to keep a copy for Undo", async () => {
    const fetch = vi.fn(async (_url: string) => new Response("hello", { status: 200, headers: { "Content-Type": "text/markdown" } }));
    vi.stubGlobal("fetch", fetch);
    const file = await downloadDocument({ id: "d 1", projectId: "p", name: "notes.md", size: 5, uploadedAt: 0, state: "ready" });
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p/documents/d%201/file");
    expect(file.name).toBe("notes.md");
    expect(await file.text()).toBe("hello");
  });

  it("shows the BFF's own reason for a refused file", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Files are limited to 16 MB." }), { status: 413 })));
    const error = await uploadDocument("main", Object.assign(new Blob(["x"]), { name: "a.pdf" })).catch((e) => e);
    expect(error).toBeInstanceOf(DocumentApiError);
    expect(documentErrorMessage(error)).toBe("Files are limited to 16 MB.");
    expect(documentErrorMessage(new DocumentApiError("unknown", 404))).toMatch(/no longer exists/);
  });
});
