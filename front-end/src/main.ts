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

  if (items.length === 0) {
    const empty = el("div", { className: "empty-state" }, [
      el("div", { className: "empty-state-icon" }, ["\u2728"]),
      el("p", {}, ["Ask a question about PeopleSoft Financials to get started."]),
    ]);
    container.append(empty);
    return;
  }

  for (const m of items) {
    if (m.kind === "user") {
      container.append(el("div", { className: "bubble user" }, [m.text]));
    } else if (m.kind === "assistant") {
      const inner = el("div", { className: "bubble assistant" });
      const tag = el("div", { className: "role-tag" }, [
        el("i", { className: "role-icon" }, ["\u2726"]),
        "Assistant",
      ]);
      inner.append(tag);
      inner.append(document.createTextNode(m.text));
      container.append(inner);
    } else {
      const inner = el("div", { className: "bubble tool" });
      const tag = el("div", { className: "role-tag" }, [
        el("i", { className: "role-icon" }, ["\u2699"]),
        `Tool \u00b7 ${m.name}`,
      ]);
      inner.append(tag, document.createTextNode(m.detail));
      container.append(inner);
    }
  }
  container.scrollTop = container.scrollHeight;
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "…" : s;
}

async function consumeSSEStream(
  res: Response,
  history: UiMessage[],
  messagesEl: HTMLElement,
  setStatus: (text: string, ok?: boolean, err?: boolean) => void,
): Promise<string> {
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let replyText = "";
  const toolBubbleMap: Record<number, number> = {};

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value;

    const parts = buffer.split("\n\n");
    buffer = parts.pop()!;

    for (const part of parts) {
      if (!part.trim()) continue;
      let eventType = "";
      let dataStr = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) eventType = line.slice(7);
        else if (line.startsWith("data: ")) dataStr = line.slice(6);
      }
      if (!dataStr) continue;

      const parsed = JSON.parse(dataStr);

      switch (eventType) {
        case "status":
          setStatus(parsed.message);
          break;

        case "tool_start": {
          const argsStr = truncate(JSON.stringify(parsed.args), 600);
          toolBubbleMap[parsed.index] = history.length;
          history.push({
            kind: "tool",
            name: parsed.name,
            detail: `${argsStr}\n\n⏳ Running…`,
          });
          renderMessages(messagesEl, history);
          break;
        }

        case "tool_result": {
          const argsStr = truncate(JSON.stringify(parsed.args), 600);
          const preview = truncate(parsed.result, 1200);
          const idx = toolBubbleMap[parsed.index];
          if (idx !== undefined && history[idx]?.kind === "tool") {
            history[idx] = {
              kind: "tool",
              name: parsed.name,
              detail: `${argsStr}\n\n→ ${preview}`,
            };
          } else {
            history.push({
              kind: "tool",
              name: parsed.name,
              detail: `${argsStr}\n\n→ ${preview}`,
            });
          }
          renderMessages(messagesEl, history);
          break;
        }

        case "text":
          replyText = parsed.text;
          history.push({ kind: "assistant", text: replyText });
          renderMessages(messagesEl, history);
          break;

        case "done":
          break;

        case "error":
          throw new Error(parsed.error);
      }
    }
  }
  return replyText;
}

async function main() {
  const history: UiMessage[] = [];
  const chatHistory: { role: string; content: string }[] = [];

  const root = document.getElementById("app");
  if (!root) return;

  const statusDot = el("span", { className: "status-dot" });
  const statusEl = el("div", { className: "status ok" }, [statusDot, "Ready"]);
  const messagesEl = el("div", { className: "messages" });
  const textarea = el("textarea", {
    placeholder: "Ask about journals, vendors, GL accounts, PeopleTools records…",
    rows: "3",
  }) as HTMLTextAreaElement;
  const sendBtn = el("button", { className: "btn btn-primary", type: "button" }, [
    "Send",
  ]) as HTMLButtonElement;
  const clearBtn = el("button", { className: "btn btn-clear", type: "button" }, [
    "Clear Chat",
  ]) as HTMLButtonElement;

  const setStatus = (text: string, ok?: boolean, err?: boolean) => {
    statusEl.replaceChildren(statusDot, text);
    const busy = !ok && !err;
    statusEl.className = "status" + (ok ? " ok" : "") + (err ? " err" : "") + (busy ? " busy" : "");
  };

  const composerEl = el("div", { className: "composer" }, [
    el("p", { className: "hint" }, [
      "Shift+Enter for newline \u00b7 Enter to send",
    ]),
    el("div", { className: "composer-row" }, [textarea, sendBtn, clearBtn]),
  ]);

  clearBtn.addEventListener("click", () => {
    history.length = 0;
    chatHistory.length = 0;
    renderMessages(messagesEl, history);
    setStatus("Chat cleared — Ready", true);
  });

  const runSend = async () => {
    const text = textarea.value.trim();
    if (!text) return;

    textarea.value = "";
    history.push({ kind: "user", text });
    renderMessages(messagesEl, history);

    sendBtn.disabled = true;
    composerEl.classList.add("sending");
    setStatus("Sending…");

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: chatHistory }),
      });

      const contentType = res.headers.get("content-type") || "";

      if (contentType.includes("text/event-stream") && res.body) {
        const replyText = await consumeSSEStream(
          res,
          history,
          messagesEl,
          setStatus,
        );
        if (replyText) {
          chatHistory.push({ role: "user", content: text });
          chatHistory.push({ role: "assistant", content: replyText });
        }
        setStatus("Ready", true);
      } else {
        const raw = await res.text();
        if (!raw) {
          throw new Error(
            `Server returned empty response (HTTP ${res.status}). Is the backend running?`,
          );
        }
        let data: ChatResponse;
        try {
          data = JSON.parse(raw) as ChatResponse;
        } catch {
          throw new Error(
            `Server returned non-JSON (HTTP ${res.status}): ${raw.slice(0, 200)}`,
          );
        }

        if (data.error) {
          throw new Error(data.error);
        }

        if (data.tool_calls) {
          for (const tc of data.tool_calls) {
            history.push({
              kind: "tool",
              name: tc.name,
              detail: `${truncate(JSON.stringify(tc.args), 600)}\n\n→ ${truncate(tc.result, 1200)}`,
            });
          }
        }
        const reply = data.reply || "(No response)";
        history.push({ kind: "assistant", text: reply });
        renderMessages(messagesEl, history);

        chatHistory.push({ role: "user", content: text });
        chatHistory.push({ role: "assistant", content: reply });
        setStatus("Ready", true);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      history.push({ kind: "assistant", text: `Error: ${msg}` });
      renderMessages(messagesEl, history);
      setStatus(msg, false, true);
    } finally {
      sendBtn.disabled = false;
      composerEl.classList.remove("sending");
    }
  };

  sendBtn.addEventListener("click", () => void runSend());
  textarea.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      void runSend();
    }
  });

  renderMessages(messagesEl, history);

  root.append(
    el("div", { className: "layout" }, [
      el("aside", { className: "panel" }, [
        el("div", {}, [
          el("h1", {}, ["PeopleSoft Finance"]),
          el("p", { className: "sub" }, [
            "Chat with the AI Assistant",
          ]),
        ]),
        el("div", {}, [el("label", {}, ["Status"]), statusEl]),
      ]),
      el("main", { className: "chat-wrap" }, [
        messagesEl,
        composerEl,
      ]),
    ]),
  );
}

void main();
