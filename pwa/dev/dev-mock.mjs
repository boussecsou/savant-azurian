// `npm run dev:mock`: the mock backend plus the Vite dev server wired to it. No Azure, no sign-in.
import { spawn } from "node:child_process";
import { createMockBff } from "./mock-bff.mjs";

const port = Number(process.env.MOCK_BFF_PORT ?? 8091);
createMockBff().listen(port, "127.0.0.1", () => console.log(`Mock backend on http://127.0.0.1:${port} (canned replies)`));

const vite = spawn("npx", ["vite", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, SA2_BFF_URL: `http://127.0.0.1:${port}`, SA2_BFF_APP_ID_URI: "" },
  shell: process.platform === "win32",
});
vite.on("exit", (code) => process.exit(code ?? 0));
