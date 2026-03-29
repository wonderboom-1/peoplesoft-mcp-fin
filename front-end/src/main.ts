import "./style.css";

type UiMessage =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tool"; name: string; detail: string };

type ChatResponse = {
  reply?: string;
  error?: string;
  tool_calls?: { name: string; args: Record<string, unknown>; result: string }[];
};

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  children: (string | Node)[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "className") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    node.append(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function renderMessages(container: HTMLElement, items: UiMessage[]) {
  container.replaceChildren();
  for (const m of items) {
    if (m.kind === "user") {
      container.append(el("div", { className: "bubble user" }, [m.text]));
    } else if (m.kind === "assistant") {
      const inner = el("div", { className: "bubble assistant" });
      inner.append(el("div", { className: "role-tag" }, ["Assistant"]));
      inner.append(document.createTextNode(m.text));
      container.append(inner);
    } else {
      const inner = el("div", { className: "bubble tool" });
      inner.append(
        el("div", { className: "role-tag" }, [`Tool · ${m.name}`]),
        document.createTextNode(m.detail),
      );
      container.append(inner);
    }
  }
  container.scrollTop = container.scrollHeight;
}

async function main() {
  const history: UiMessage[] = [];
  const chatHistory: { role: string; content: string }[] = [];

  const root = document.getElementById("app");
  if (!root) return;

  const statusEl = el("div", { className: "status" }, ["Ready"]);
  const messagesEl = el("div", { className: "messages" });
  const textarea = el("textarea", {
    placeholder: "Ask about journals, vendors, GL accounts, PeopleTools records…",
    rows: "3",
  }) as HTMLTextAreaElement;
  const sendBtn = el("button", { className: "btn btn-primary", type: "button" }, [
    "Send",
  ]) as HTMLButtonElement;

  const setStatus = (text: string, ok?: boolean, err?: boolean) => {
    statusEl.textContent = text;
    statusEl.className = "status" + (ok ? " ok" : "") + (err ? " err" : "");
  };

  const runSend = async () => {
    const text = textarea.value.trim();
    if (!text) return;

    textarea.value = "";
    history.push({ kind: "user", text });
    renderMessages(messagesEl, history);

    sendBtn.disabled = true;
    setStatus("Calling LLM + MCP tools…");

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: chatHistory }),
      });

      const raw = await res.text();
      if (!raw) {
        throw new Error(`Server returned empty response (HTTP ${res.status}). Is the backend running?`);
      }
      let data: ChatResponse;
      try {
        data = JSON.parse(raw) as ChatResponse;
      } catch {
        throw new Error(`Server returned non-JSON (HTTP ${res.status}): ${raw.slice(0, 200)}`);
      }

      if (data.error) {
        history.push({ kind: "assistant", text: `Error: ${data.error}` });
        renderMessages(messagesEl, history);
        setStatus(data.error, false, true);
        return;
      }

      if (data.tool_calls) {
        for (const tc of data.tool_calls) {
          const argsStr = JSON.stringify(tc.args);
          const preview =
            tc.result.length > 1200 ? `${tc.result.slice(0, 1200)}…` : tc.result;
          history.push({
            kind: "tool",
            name: tc.name,
            detail: `${argsStr.length > 600 ? argsStr.slice(0, 600) + "…" : argsStr}\n\n→ ${preview}`,
          });
        }
      }

      const reply = data.reply || "(No response)";
      history.push({ kind: "assistant", text: reply });
      renderMessages(messagesEl, history);

      chatHistory.push({ role: "user", content: text });
      chatHistory.push({ role: "assistant", content: reply });

      setStatus("Ready", true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      history.push({ kind: "assistant", text: `Error: ${msg}` });
      renderMessages(messagesEl, history);
      setStatus(msg, false, true);
    } finally {
      sendBtn.disabled = false;
    }
  };

  sendBtn.addEventListener("click", () => void runSend());
  textarea.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      void runSend();
    }
  });

  root.append(
    el("div", { className: "layout" }, [
      el("aside", { className: "panel" }, [
        el("div", {}, [
          el("h1", {}, ["PeopleSoft Finance"]),
          el("p", { className: "sub" }, [
            "Chat UI · LLM + MCP tools run server-side.",
          ]),
        ]),
        el("div", {}, [el("label", {}, ["Status"]), statusEl]),
        el("p", { className: "hint" }, [
          "The Python backend calls Claude on Azure AI Foundry and executes MCP ",
          "tools locally. Configure ",
          el("code", {}, ["MICROSOFT_FOUNDRY_API_KEY"]),
          " and ",
          el("code", {}, ["MICROSOFT_FOUNDRY_BASE_URL"]),
          " in the root ",
          el("code", {}, [".env"]),
          " file.",
        ]),
        el("p", { className: "hint" }, [
          "Run the Python server with HTTP transport on port 8766: ",
          el("code", {}, [
            "PEOPLESOFT_FIN_MCP_TRANSPORT=http PEOPLESOFT_FIN_MCP_HTTP_PORT=8766 uv run peoplesoft_fin_server.py",
          ]),
          ". Then ",
          el("code", {}, ["npm run dev"]),
          " in the front-end folder.",
        ]),
      ]),
      el("main", { className: "chat-wrap" }, [
        messagesEl,
        el("div", { className: "composer" }, [
          el("p", { className: "hint" }, [
            "Shift+Enter for newline · Enter to send",
          ]),
          el("div", { className: "composer-row" }, [textarea, sendBtn]),
        ]),
      ]),
    ]),
  );
}

void main();
