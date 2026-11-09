import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import { createTokenProvider, type RunAz } from "./token";

/**
 * Local dev only: before Vite's proxy forwards /api to the BFF, replace any
 * Authorization header with the owner's Entra token (the BFF sits behind Easy Auth).
 */
export function bffAuth(resource: string, run?: RunAz): Plugin {
  const getToken = createTokenProvider(resource, run);
  return {
    name: "sa2-bff-auth",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/api", (req: IncomingMessage, res: ServerResponse, next: (error?: unknown) => void) => {
        getToken().then(
          (token) => {
            req.headers.authorization = `Bearer ${token}`;
            next();
          },
          (error: unknown) => {
            server.config.logger.error(`[sa2] ${error instanceof Error ? error.message : "Token error"}`);
            res.statusCode = 401;
            res.setHeader("Cache-Control", "no-store");
            res.end();
          },
        );
      });
    },
  };
}
