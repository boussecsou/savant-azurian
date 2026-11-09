import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import { bffAuth } from "./dev/plugin";

/**
 * Local development talks to the real BFF on Azure Container Apps:
 *   SA2_BFF_URL         https://<bff>.<region>.azurecontainerapps.io
 *   SA2_BFF_APP_ID_URI  api://<application-id of the BFF's Entra app registration>
 * Put them in pwa/.env.local (git-ignored). Without SA2_BFF_APP_ID_URI no token is added
 * (useful against a BFF running on localhost).
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "SA2_");
  const target = env.SA2_BFF_URL?.trim().replace(/\/+$/, "");
  const resource = env.SA2_BFF_APP_ID_URI?.trim();
  if (target) {
    const url = new URL(target);
    const local = ["localhost", "127.0.0.1"].includes(url.hostname);
    if (url.protocol !== "https:" && !(local && url.protocol === "http:")) {
      throw new Error("SA2_BFF_URL must be HTTPS (HTTP is only allowed for localhost).");
    }
  }
  return {
    plugins: [react(), ...(target && resource ? [bffAuth(resource)] : [])],
    build: { target: "es2022" },
    server: target ? { proxy: { "/api": { target, changeOrigin: true } } } : {},
    test: { environment: "node", include: ["src/**/*.test.{ts,tsx}", "dev/**/*.test.ts"] },
  };
});
