import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.MCP_PROXY_TARGET || "http://localhost:8765";

  return {
    server: {
      proxy: {
        "/mcp": { target, changeOrigin: true },
        "/chat": { target, changeOrigin: true },
      },
    },
  };
});
