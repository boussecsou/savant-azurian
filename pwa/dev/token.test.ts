import { describe, expect, it, vi } from "vitest";
import { createTokenProvider, TokenError } from "./token";

const reply = (token: string, expiresInSeconds: number, now: number) =>
  JSON.stringify({ accessToken: token, expires_on: Math.floor(now / 1000) + expiresInSeconds });

describe("createTokenProvider", () => {
  it("asks the Azure CLI for the configured resource and caches the token", async () => {
    let now = 1_000_000_000_000;
    const run = vi.fn(async () => reply("t1", 3600, now));
    const getToken = createTokenProvider("api://sa2-bff", run, () => now);
    await expect(getToken()).resolves.toBe("t1");
    now += 30 * 60 * 1000;
    await expect(getToken()).resolves.toBe("t1");
    expect(run).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledWith(["account", "get-access-token", "--resource", "api://sa2-bff", "-o", "json"]);
  });

  it("refreshes shortly before expiry", async () => {
    let now = 1_000_000_000_000;
    const run = vi.fn().mockImplementationOnce(async () => reply("t1", 3600, now)).mockImplementationOnce(async () => reply("t2", 3600, now));
    const getToken = createTokenProvider("api://sa2-bff", run, () => now);
    await getToken();
    now += 59 * 60 * 1000;
    await expect(getToken()).resolves.toBe("t2");
  });

  it("shares one CLI call between concurrent requests", async () => {
    const now = 1_000_000_000_000;
    const run = vi.fn(async () => reply("t1", 3600, now));
    const getToken = createTokenProvider("api://sa2-bff", run, () => now);
    await expect(Promise.all([getToken(), getToken(), getToken()])).resolves.toEqual(["t1", "t1", "t1"]);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("explains how to recover without leaking CLI output", async () => {
    const run = vi.fn<() => Promise<string>>(async () => {
      throw Object.assign(new Error("ERROR: tenant 1234 secret detail"), { stderr: "tenant 1234" });
    });
    const getToken = createTokenProvider("api://sa2-bff", run);
    const failure = await getToken().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(TokenError);
    expect((failure as Error).message).toContain("az login");
    expect((failure as Error).message).not.toContain("1234");
    // A failure is not cached: the next request tries again.
    run.mockImplementationOnce(async () => reply("t2", 3600, Date.now()));
    await expect(getToken()).resolves.toBe("t2");
  });

  it.each(["not json", "{}", JSON.stringify({ accessToken: "" })])("rejects an unusable CLI answer (%s)", async (output) => {
    const getToken = createTokenProvider("api://sa2-bff", async () => output);
    await expect(getToken()).rejects.toBeInstanceOf(TokenError);
  });
});
