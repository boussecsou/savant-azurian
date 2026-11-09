/**
 * Voice mode: what the browser says aloud, without asking the model, while the agent works.
 * Fixed phrases keyed on the tool name only (arguments and results never leave the BFF), one when
 * a tool starts and one when its result comes back. A repeated tool gets a different phrase each
 * time. A tool that may wait for the owner's confirmation is announced as "preparing", and its
 * end only says the result is being checked: never that something was done.
 * French by default; English when the owner spoke English.
 */
import { outlookOperation } from "./tools";

type Phrase = readonly [fr: string, en: string];

interface Lines {
  /** First phrase for this exact tool, then variants for the next calls of the same kind. */
  start: readonly Phrase[];
  done: readonly Phrase[];
}

const SEARCH_DONE: readonly Phrase[] = [
  ["Voilà, je regarde les résultats.", "Here we go, looking at the results."],
  ["C'est revenu, je jette un œil.", "It's back, taking a look."],
  ["J'ai la réponse, je vérifie.", "Got it, checking."],
];
const READ_DONE: readonly Phrase[] = [
  ["C'est bon, je l'ai.", "Got it."],
  ["Voilà, c'est lu.", "Done reading."],
  ["Parfait, je regarde ça.", "Great, looking at it."],
];
// Writes, commands and code may only be waiting for confirmation: never claim they ran.
const CHECK_DONE: readonly Phrase[] = [
  ["Je regarde le résultat.", "Checking the result."],
  ["Voyons ce que ça donne.", "Let's see how it went."],
  ["Je vérifie le retour.", "Checking what came back."],
];

const WEB: Lines = {
  start: [
    ["Je cherche ça sur le web.", "Let me look that up online."],
    ["Je lance une autre recherche.", "Running another search."],
    ["Je creuse encore un peu.", "Digging a little deeper."],
  ],
  done: SEARCH_DONE,
};
const NOTION_SEARCH: Lines = {
  start: [
    ["Je cherche dans ton Notion.", "Searching your Notion."],
    ["Je fais une autre recherche dans Notion.", "Another search in Notion."],
    ["Je cherche encore dans Notion.", "Still searching Notion."],
  ],
  done: SEARCH_DONE,
};
const NOTION_READ_MORE: readonly Phrase[] = [
  ["Je lis la suite.", "Reading on."],
  ["Je jette un œil à autre chose.", "Looking at one more thing."],
];
const NOTION_WRITE_MORE: readonly Phrase[] = [
  ["Je prépare une autre modification.", "Preparing another change."],
  ["J'enchaîne avec la suite.", "Moving on to the next step."],
];
const SSH: Lines = {
  start: [
    ["Je lance une commande sur la machine virtuelle.", "Running a command on the VM."],
    ["J'enchaîne avec une autre commande.", "Another command coming up."],
    ["Encore une commande sur la machine.", "One more command on the machine."],
    ["Je continue sur la machine virtuelle.", "Still working on the VM."],
  ],
  done: [
    ["Commande terminée, je regarde.", "Command finished, checking."],
    ["C'est revenu de la machine.", "The machine answered."],
    ["Je lis la sortie.", "Reading the output."],
  ],
};
// The project's sources may be PDFs, slides, notes or text: speak of "sources", not of one file type.
const DOCUMENTS: Lines = {
  start: [
    ["Je regarde ça dans les sources du projet.", "Let me check the project's sources."],
    ["Je cherche encore dans tes sources.", "Searching your sources again."],
    ["Je fouille un autre point dans les sources.", "Looking up another point in the sources."],
  ],
  done: [
    ["Voilà, je lis ce que disent les sources.", "Here we go, reading what the sources say."],
    ["J'ai les passages, je regarde.", "Got the passages, taking a look."],
    ["C'est revenu des sources, je vérifie.", "The sources answered, checking."],
  ],
};
const GENERIC: Lines = {
  start: [
    ["Je m'en occupe.", "On it."],
    ["Je continue.", "Carrying on."],
    ["Encore une petite étape.", "One more small step."],
  ],
  done: CHECK_DONE,
};

function notionRead(first: Phrase): Lines {
  return { start: [first, ...NOTION_READ_MORE], done: READ_DONE };
}
function notionWrite(first: Phrase): Lines {
  return { start: [first, ...NOTION_WRITE_MORE], done: CHECK_DONE };
}

const TOOLS: Record<string, Lines> = {
  "notion-search": NOTION_SEARCH,
  "notion-fetch": notionRead(["Je lis la page.", "Reading the page."]),
  "notion-query-data-sources": notionRead(["Je consulte ta base de données.", "Checking your database."]),
  "notion-query-multiple-data-sources": notionRead(["Je consulte tes bases de données.", "Checking your databases."]),
  "notion-query-meeting-notes": notionRead(["Je lis tes notes de réunion.", "Reading your meeting notes."]),
  "notion-get-comments": notionRead(["Je lis les commentaires.", "Reading the comments."]),
  "notion-get-users": notionRead(["Je vérifie dans Notion.", "Checking Notion."]),
  "notion-get-teams": notionRead(["Je vérifie dans Notion.", "Checking Notion."]),
  "notion-get-self": notionRead(["Je vérifie dans Notion.", "Checking Notion."]),
  "notion-get-tool-access": notionRead(["Je vérifie mes accès à Notion.", "Checking my Notion access."]),
  "notion-create-pages": notionWrite(["Je prépare la page.", "Preparing the page."]),
  "notion-update-page": notionWrite(["Je prépare la modification.", "Preparing the update."]),
  "notion-create-comment": notionWrite(["Je prépare le commentaire.", "Preparing the comment."]),
  "notion-create-database": notionWrite(["Je prépare la base de données.", "Preparing the database."]),
  "notion-move-pages": notionWrite(["Je prépare le déplacement.", "Preparing the move."]),
  "notion-duplicate-page": notionWrite(["Je prépare la copie.", "Preparing the copy."]),
  "notion-delete-pages": notionWrite(["Je prépare la suppression.", "Preparing the deletion."]),
  connect_notion: { start: [["Je vérifie la connexion à Notion.", "Checking the Notion connection."]], done: READ_DONE },
  read_ssh_skill: {
    start: [["Je relis mes règles pour la machine virtuelle.", "Rereading my rules for the VM."]],
    done: [["C'est bon, je suis prêt.", "All set."]],
  },
  ssh_exec: SSH,
  search_documents: DOCUMENTS,
  tool_search: { start: [["Je cherche le bon outil.", "Finding the right tool."]], done: READ_DONE },
};

const OUTLOOK_READ = (first: Phrase): Lines => ({ start: [first, ["Je regarde autre chose dans ta boîte.", "Checking something else in your mailbox."]], done: READ_DONE });
const OUTLOOK_WRITE = (first: Phrase): Lines => ({ start: [first, ["Je prépare la suite.", "Preparing the next step."]], done: CHECK_DONE });

const OUTLOOK: Record<string, Lines> = {
  GetEmails: OUTLOOK_READ(["Je regarde tes e-mails.", "Checking your emails."]),
  GetEmailsV2: OUTLOOK_READ(["Je regarde tes e-mails.", "Checking your emails."]),
  GetEmail: OUTLOOK_READ(["Je lis l'e-mail.", "Reading the email."]),
  GetAttachment: OUTLOOK_READ(["Je lis la pièce jointe.", "Reading the attachment."]),
  CalendarGetTable: OUTLOOK_READ(["Je regarde ton agenda.", "Checking your calendar."]),
  ContactGetTable: OUTLOOK_READ(["Je regarde tes contacts.", "Checking your contacts."]),
  MarkAsRead: OUTLOOK_WRITE(["Je range l'e-mail.", "Tidying the email."]),
  Flag: OUTLOOK_WRITE(["Je range l'e-mail.", "Tidying the email."]),
  Move: OUTLOOK_WRITE(["Je range l'e-mail.", "Tidying the email."]),
  SendEmail: OUTLOOK_WRITE(["Je prépare l'e-mail.", "Preparing the email."]),
  SendEmailV2: OUTLOOK_WRITE(["Je prépare l'e-mail.", "Preparing the email."]),
  ReplyToV3: OUTLOOK_WRITE(["Je prépare la réponse.", "Preparing the reply."]),
  DeleteEmail: OUTLOOK_WRITE(["Je prépare la suppression.", "Preparing the deletion."]),
};

const CODE: Lines = {
  start: [
    ["Je prépare un petit calcul.", "Preparing a quick calculation."],
    ["Je prépare un autre calcul.", "Preparing another calculation."],
  ],
  done: CHECK_DONE,
};

/** The phrase family for a tool, and the key that groups its repeats. */
function linesFor(name: string | undefined): { key: string; lines: Lines } {
  if (name) {
    const known = TOOLS[name];
    if (known) return { key: name, lines: known };
    const operation = outlookOperation(name);
    if (operation) return { key: `outlook:${operation}`, lines: OUTLOOK[operation] ?? GENERIC };
    if (/^web_search(_|$)/.test(name)) return { key: "web", lines: WEB };
    if (/^code_interpreter(_|$)/.test(name)) return { key: "code", lines: CODE };
  }
  return { key: "generic", lines: GENERIC };
}

export type ToolMoment = "start" | "done";

/** Said once when voice mode starts. Neutral on purpose: no "bonjour"/"bonsoir", it can be any hour. */
const GREETINGS: readonly Phrase[] = [
  ["Salut, je t'écoute.", "Hi, I'm listening."],
  ["Coucou, je suis là.", "Hey, I'm here."],
  ["Salut ! Dis-moi tout.", "Hi! Tell me everything."],
  ["Hello, qu'est-ce que je peux faire pour toi ?", "Hello, what can I do for you?"],
  ["Je t'écoute.", "I'm listening."],
];

/**
 * Said at once after each request, before the agent has read it: it only confirms reception. Never a
 * claim of understanding ("Je vois", "Compris") or an opinion ("Très bien"): the agent has not weighed in yet.
 */
const ACKNOWLEDGMENTS: readonly Phrase[] = [
  ["D'accord.", "Okay."],
  ["Bien reçu.", "Received."],
  ["C'est noté.", "Noted."],
];

/** A random index below `length`, never `previous` (so the same phrase does not come twice in a row). */
export function pickIndex(length: number, rng: () => number = Math.random, previous?: number): number {
  if (length <= 1) return 0;
  const skip = previous !== undefined && previous < length;
  const index = Math.floor(rng() * (length - (skip ? 1 : 0)));
  return skip && index >= previous ? index + 1 : index;
}

export function spokenGreeting(language: string | undefined, rng: () => number = Math.random): string {
  return pick(GREETINGS[pickIndex(GREETINGS.length, rng)], language);
}

export function spokenAcknowledgment(language: string | undefined, rng: () => number = Math.random, previous?: number): { text: string; index: number } {
  const index = pickIndex(ACKNOWLEDGMENTS.length, rng, previous);
  return { text: pick(ACKNOWLEDGMENTS[index], language), index };
}

function pick(phrase: Phrase, language: string | undefined): string {
  return language?.toLowerCase().startsWith("en") ? phrase[1] : phrase[0];
}

/** The phrase for the n-th call (0-based) of a tool, cycling through its variants. */
export function spokenToolPhrase(name: string | undefined, language: string | undefined, moment: ToolMoment = "start", n = 0): string {
  const phrases = linesFor(name).lines[moment];
  return pick(phrases[n % phrases.length], language);
}

/** Minimum pause between two announcements. */
export const NARRATION_GAP_MS = 600;
/** Announcements waiting behind the one being spoken; older ones are dropped beyond this. */
export const NARRATION_BACKLOG = 2;

/**
 * One voice turn's announcements: a different phrase each time the same tool repeats, and a short
 * waiting line (the oldest waiting phrase is dropped, so speech never lags far behind the agent).
 */
export class NarrationQueue {
  private counts = new Map<string, number>();
  private waiting: string[] = [];

  constructor(private readonly language: string | undefined) {}

  /** Queue a random acknowledgment ("Bien reçu.") and return its index, to avoid repeating it next turn. */
  acknowledge(previous?: number, rng: () => number = Math.random): number {
    const { text, index } = spokenAcknowledgment(this.language, rng, previous);
    this.waiting.push(text);
    return index;
  }

  /** Queue the phrase for this tool event and return it. */
  offer(name: string | undefined, moment: ToolMoment): string {
    const key = `${linesFor(name).key}:${moment}`;
    const n = this.counts.get(key) ?? 0;
    this.counts.set(key, n + 1);
    const phrase = spokenToolPhrase(name, this.language, moment, n);
    this.waiting.push(phrase);
    if (this.waiting.length > NARRATION_BACKLOG) this.waiting.shift();
    return phrase;
  }

  take(): string | null {
    return this.waiting.shift() ?? null;
  }

  clear(): void {
    this.waiting = [];
  }
}
