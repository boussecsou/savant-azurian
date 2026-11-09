import { useCallback, useState } from "react";
import { isOutlookTool } from "./tools";

/**
 * Outlook is authorised in Foundry per signed-in identity, and the BFF cannot read that status.
 * The browser therefore learns it from the agent's own tool calls: a finished Outlook call means
 * connected, the sign-in tool means it is not. The mark lives in localStorage so a reload keeps it.
 */
export type OutlookState = "unknown" | "disconnected" | "connected";

/**
 * Outlook is set aside for now: its toolbox source fails for the BFF caller, so the agent uses the
 * web-only toolbox. Flip this back once Outlook works through the BFF.
 */
export const OUTLOOK_ENABLED = false;

export const OUTLOOK_KEY = "sa2-outlook";
export const CONSENT_TOOL = "oauth_consent_required";

/** What a finished tool call says about the connection, or null when it says nothing. */
export function outlookStateAfterTool(name: string | undefined, askedForSignIn = false): OutlookState | null {
  if (name === CONSENT_TOOL) return "disconnected";
  if (!isOutlookTool(name)) return null;
  // The toolbox answers an unauthorised connector with a sign-in link: the call finished, but nothing was read.
  return askedForSignIn ? "disconnected" : "connected";
}

function storage(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function readOutlook(store: Pick<Storage, "getItem"> | undefined = storage()): OutlookState {
  try {
    const raw = store?.getItem(OUTLOOK_KEY);
    return raw === "connected" || raw === "disconnected" ? raw : "unknown";
  } catch {
    return "unknown";
  }
}

export function useOutlook() {
  const [state, setState] = useState<OutlookState>(() => readOutlook());

  const observeTool = useCallback((name: string | undefined, askedForSignIn = false) => {
    const next = outlookStateAfterTool(name, askedForSignIn);
    if (!next) return;
    setState(next);
    try {
      storage()?.setItem(OUTLOOK_KEY, next);
    } catch {
      // Storage blocked: the state then lasts for this page only.
    }
  }, []);

  return { state, observeTool };
}
