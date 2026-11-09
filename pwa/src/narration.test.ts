import { describe, expect, it } from "vitest";
import { NARRATION_BACKLOG, NarrationQueue, pickIndex, spokenAcknowledgment, spokenGreeting, spokenToolPhrase } from "./narration";

describe("spokenToolPhrase", () => {
  it("speaks French by default and English when the owner spoke English", () => {
    expect(spokenToolPhrase("notion-search", undefined)).toBe("Je cherche dans ton Notion.");
    expect(spokenToolPhrase("notion-search", "fr-FR")).toBe("Je cherche dans ton Notion.");
    expect(spokenToolPhrase("notion-search", "en-US")).toBe("Searching your Notion.");
  });

  it("recognizes web search, code and Outlook tools by their toolbox names", () => {
    expect(spokenToolPhrase("web_search_preview", "fr-FR")).toBe("Je cherche ça sur le web.");
    expect(spokenToolPhrase("code_interpreter", "fr-FR")).toBe("Je prépare un petit calcul.");
    expect(spokenToolPhrase("sa2___outlook_GetEmailsV2", "fr-FR")).toBe("Je regarde tes e-mails.");
  });

  it("varies the phrase when the same tool repeats, then cycles", () => {
    const first = spokenToolPhrase("ssh_exec", "fr-FR", "start", 0);
    const second = spokenToolPhrase("ssh_exec", "fr-FR", "start", 1);
    expect(second).not.toBe(first);
    expect(spokenToolPhrase("ssh_exec", "fr-FR", "start", 4)).toBe(first);
  });

  it("never claims a write, a command or code ran: they may wait for confirmation", () => {
    for (const name of ["notion-delete-pages", "notion-update-page", "ssh_exec", "sa2___outlook_SendEmailV2", "code_interpreter"]) {
      for (let n = 0; n < 4; n++) {
        const start = spokenToolPhrase(name, "fr-FR", "start", n);
        const done = spokenToolPhrase(name, "fr-FR", "done", n);
        expect(start).not.toMatch(/supprimé|envoyé|créé|modifié|exécuté/);
        expect(done).not.toMatch(/supprimé|envoyé|créé|modifié|exécuté|réussi/);
      }
      expect(spokenToolPhrase(name, "fr-FR", "start", 0)).toMatch(/^Je (prépare|lance)/);
    }
  });

  it("falls back to a neutral phrase for unknown or missing names", () => {
    expect(spokenToolPhrase("brand_new_tool", "fr-FR")).toBe("Je m'en occupe.");
    expect(spokenToolPhrase(undefined, "en-US")).toBe("On it.");
  });
});

describe("NarrationQueue", () => {
  it("announces every call of a repeated tool, each with the next variant", () => {
    const queue = new NarrationQueue("fr-FR");
    const a = queue.offer("ssh_exec", "start");
    expect(queue.take()).toBe(a);
    const b = queue.offer("ssh_exec", "start");
    expect(b).not.toBe(a);
    expect(queue.take()).toBe(b);
  });

  it("counts starts and ends separately and says when a result comes back", () => {
    const queue = new NarrationQueue(undefined);
    queue.offer("web_search", "start");
    queue.offer("web_search", "done");
    expect(queue.take()).toBe("Je cherche ça sur le web.");
    expect(queue.take()).toBe("Voilà, je regarde les résultats.");
    expect(queue.take()).toBeNull();
  });

  it("drops the oldest waiting phrase so speech never lags far behind", () => {
    const queue = new NarrationQueue("fr-FR");
    for (let n = 0; n < NARRATION_BACKLOG + 2; n++) queue.offer("ssh_exec", "start");
    const waiting = [];
    for (let phrase = queue.take(); phrase; phrase = queue.take()) waiting.push(phrase);
    expect(waiting).toHaveLength(NARRATION_BACKLOG);
    queue.offer("notion-fetch", "start");
    queue.clear();
    expect(queue.take()).toBeNull();
  });
});

describe("pickIndex", () => {
  it("stays in range and never returns the previous index", () => {
    for (let previous = 0; previous < 6; previous++) {
      for (const draw of [0, 0.2, 0.5, 0.99999]) {
        const index = pickIndex(6, () => draw, previous);
        expect(index).toBeGreaterThanOrEqual(0);
        expect(index).toBeLessThan(6);
        expect(index).not.toBe(previous);
      }
    }
  });

  it("covers every other index across the range of draws", () => {
    const seen = new Set<number>();
    for (let i = 0; i < 100; i++) seen.add(pickIndex(6, () => i / 100, 2));
    expect([...seen].sort()).toEqual([0, 1, 3, 4, 5]);
  });

  it("copes with a single phrase", () => {
    expect(pickIndex(1, () => 0.7, 0)).toBe(0);
  });
});

describe("greeting and acknowledgment", () => {
  it("greets in French by default and in English when asked", () => {
    expect(spokenGreeting("fr-FR", () => 0)).toBe("Salut, je t'écoute.");
    expect(spokenGreeting("en-US", () => 0)).toBe("Hi, I'm listening.");
  });

  it("acknowledges with a short phrase from the list, in the owner's language", () => {
    expect(spokenAcknowledgment("fr-FR", () => 0).text).toBe("D'accord.");
    expect(spokenAcknowledgment("fr-FR", () => 0.4).text).toBe("Bien reçu.");
    expect(spokenAcknowledgment("fr-FR", () => 0.9).text).toBe("C'est noté.");
    expect(spokenAcknowledgment("en-US", () => 0).text).toBe("Okay.");
  });

  it("does not repeat the previous acknowledgment", () => {
    const first = spokenAcknowledgment("fr-FR", () => 0);
    for (const draw of [0, 0.1, 0.5, 0.99]) {
      expect(spokenAcknowledgment("fr-FR", () => draw, first.index).index).not.toBe(first.index);
    }
  });

  it("never promises or claims an action", () => {
    for (let i = 0; i < 20; i++) {
      expect(spokenAcknowledgment("fr-FR", () => i / 20).text).not.toMatch(/supprimé|envoyé|créé|modifié|exécuté|terminé/);
    }
  });
});

describe("acknowledgments only confirm reception", () => {
  // Said before the agent has read the request: never a claim of understanding or an opinion on it.
  it("never says it understood, saw or approved the request", () => {
    for (let i = 0; i < 40; i++) {
      for (const language of ["fr-FR", "en-US"]) {
        expect(spokenAcknowledgment(language, () => i / 40).text).not.toMatch(/je vois|compris|entendu|ça marche|très bien|i see|got it|understood|sounds good|alright/i);
      }
    }
  });
});

describe("NarrationQueue.acknowledge", () => {
  it("speaks the acknowledgment first, then the tool announcements, in order", () => {
    const queue = new NarrationQueue("fr-FR");
    queue.acknowledge(undefined, () => 0);
    queue.offer("web_search", "start");
    expect(queue.take()).toBe("D'accord.");
    expect(queue.take()).toBe("Je cherche ça sur le web.");
    expect(queue.take()).toBeNull();
  });

  it("returns the index so the next turn can avoid it", () => {
    const queue = new NarrationQueue("fr-FR");
    expect(queue.acknowledge(undefined, () => 0)).toBe(0);
    expect(new NarrationQueue("fr-FR").acknowledge(0, () => 0)).not.toBe(0);
  });
});

describe("project sources", () => {
  it("speaks of the project's sources, distinct from the web, with a variant for each further search", () => {
    const first = spokenToolPhrase("search_documents", "fr-FR", "start", 0);
    expect(first).toBe("Je regarde ça dans les sources du projet.");
    expect(spokenToolPhrase("search_documents", "fr-FR", "start", 1)).not.toBe(first);
    expect(first).not.toBe(spokenToolPhrase("web_search_preview", "fr-FR"));
    expect(spokenToolPhrase("search_documents", "en-US", "done", 0)).toBe("Here we go, reading what the sources say.");
  });
});

