# PeopleSoft Finance · MCP chat UI

A small Vite + TypeScript single-page app that provides a chat interface for the **peoplesoft-mcp-fin** server.

All LLM integration runs **server-side** in the Python backend. The front-end simply sends user messages to the `/chat` endpoint and displays responses (including tool call details).

## Prerequisites

- **Python MCP server** running with **HTTP** transport (not stdio). From the repo root:

  ```bash
  PEOPLESOFT_FIN_MCP_TRANSPORT=http uv run peoplesoft_fin_server.py
  ```

  Default URL: `http://localhost:8766`.

- **Azure AI Foundry** Claude deployment — set `MICROSOFT_FOUNDRY_API_KEY` and `MICROSOFT_FOUNDRY_BASE_URL` in the **root `.env`** file (see `.env.example`). The Python server reads these at runtime.

- **Node.js** 20+ recommended.

## npm and TLS (corporate networks)

If `npm install` fails with **`SELF_SIGNED_CERT_IN_CHAIN`**, it usually means TLS inspection (corporate proxy). This repo includes **`front-end/.npmrc`** with `strict-ssl=false` so installs can succeed in that environment.

On a normal network where you want strict TLS, delete the `strict-ssl=false` line from `.npmrc` (or set your org's CA via `npm config set cafile /path/to/ca.pem`).

## Run

```bash
cd front-end
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`), then chat.

## Proxy

`vite.config.ts` proxies browser requests from `/chat` and `/mcp` to the Python server. Override the target if your MCP port differs:

```bash
MCP_PROXY_TARGET=http://localhost:9000 npm run dev
```

## Security notes

- LLM credentials (`MICROSOFT_FOUNDRY_*`) and Oracle credentials stay on the Python server. The browser never sees them.
- MCP tools execute server-side; the front-end has no direct MCP or LLM access.

## Production build

`npm run build` outputs static files under `dist/`. You must serve them behind a reverse proxy that forwards `/chat` and `/mcp` to the Python server.
