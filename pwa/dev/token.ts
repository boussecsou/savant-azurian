/**
 * Entra access token for the owner, fetched with the Azure CLI session (`az login`).
 * It lives only in this local dev-server process and is added to proxied requests;
 * the browser never sees it.
 */
import { execFile } from "node:child_process";

export type RunAz = (args: string[]) => Promise<string>;

const REFRESH_MARGIN_MS = 2 * 60 * 1000;
const FALLBACK_LIFETIME_MS = 5 * 60 * 1000;

const runAz: RunAz = (args) =>
  new Promise((resolve, reject) => {
    execFile("az", args, { timeout: 30_000 }, (error, stdout) => (error ? reject(error) : resolve(stdout)));
  });

export class TokenError extends Error {}

export function createTokenProvider(resource: string, run: RunAz = runAz, now: () => number = Date.now) {
  let cached: { token: string; refreshAt: number } | undefined;
  let pending: Promise<string> | undefined;

  async function fetchToken(): Promise<string> {
    let output: string;
    try {
      output = await run(["account", "get-access-token", "--resource", resource, "-o", "json"]);
    } catch {
      // Never forward the CLI's stderr: it can echo tenant details.
      throw new TokenError("Azure CLI could not return a token. Run `az login`, then restart the dev server.");
    }
    let parsed: { accessToken?: unknown; expires_on?: unknown };
    try {
      parsed = JSON.parse(output);
    } catch {
      throw new TokenError("Unexpected output from the Azure CLI.");
    }
    if (typeof parsed.accessToken !== "string" || parsed.accessToken === "") {
      throw new TokenError("The Azure CLI returned no access token.");
    }
    const expiresOn = Number(parsed.expires_on);
    const lifetime = Number.isFinite(expiresOn) && expiresOn > 0 ? expiresOn * 1000 - now() : FALLBACK_LIFETIME_MS;
    cached = { token: parsed.accessToken, refreshAt: now() + lifetime - REFRESH_MARGIN_MS };
    return cached.token;
  }

  return async function getToken(): Promise<string> {
    if (cached && now() < cached.refreshAt) return cached.token;
    // Concurrent requests share one CLI call.
    pending ??= fetchToken().finally(() => {
      pending = undefined;
    });
    return pending;
  };
}
