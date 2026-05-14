// Vanilla JS — no framework. Three things: tab switching, chat, triage.

// ---- Per-session user_id, so AgentLoop can group turns from one demo run ----
const sessionUserId = "demo_" + Math.random().toString(36).slice(2, 10);

// ---- Tab switching ----
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("panel-" + tab.dataset.tab).classList.add("active");
  });
});

// ---- Chat tab ----
const chatHistory = document.getElementById("chat-history");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");

async function askChat(question) {
  if (!question.trim()) return;

  // Disable buttons during request
  chatSend.disabled = true;
  document.querySelectorAll(".example").forEach((b) => (b.disabled = true));

  // Render question + loading state immediately
  const item = document.createElement("div");
  item.className = "history-item";
  item.innerHTML = `
    <div class="history-question">You asked: ${escapeHtml(question)}</div>
    <div class="history-loading">Thinking...</div>
  `;
  // Newest at top
  chatHistory.prepend(item);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, user_id: sessionUserId }),
    });

    if (!res.ok) {
      const err = await res.text();
      item.querySelector(".history-loading").outerHTML =
        `<div class="history-error">Error: ${escapeHtml(err)}</div>`;
      return;
    }

    const data = await res.json();
    item.querySelector(".history-loading").outerHTML =
      `<div class="history-answer">${escapeHtml(data.answer)}</div>`;
  } catch (e) {
    item.querySelector(".history-loading").outerHTML =
      `<div class="history-error">Network error: ${escapeHtml(e.message)}</div>`;
  } finally {
    chatSend.disabled = false;
    document.querySelectorAll(".example").forEach((b) => (b.disabled = false));
    chatInput.value = "";
    chatInput.focus();
  }
}

chatSend.addEventListener("click", () => askChat(chatInput.value));
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") askChat(chatInput.value);
});
document.querySelectorAll(".example").forEach((b) => {
  b.addEventListener("click", () => askChat(b.dataset.q));
});

// ---- Triage tab ----
const triageResults = document.getElementById("triage-results");

async function classifyTicket(ticket, button) {
  button.disabled = true;
  button.querySelector(".ticket-meta").textContent = "Classifying...";

  try {
    const res = await fetch("/api/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticket, user_id: sessionUserId }),
    });

    if (!res.ok) {
      const err = await res.text();
      button.querySelector(".ticket-meta").textContent = "Error: " + err;
      return;
    }

    const data = await res.json();
    const category = data.category || "Unknown";
    const cssClass = "cat-" + category.toLowerCase();

    // Add result row
    const row = document.createElement("div");
    row.className = "triage-row";
    row.innerHTML = `
      <span class="ticket-snippet">"${escapeHtml(ticket.slice(0, 80))}${ticket.length > 80 ? "..." : ""}"</span>
      <span class="triage-category ${cssClass}">${escapeHtml(category)}</span>
    `;
    triageResults.prepend(row);

    button.querySelector(".ticket-meta").textContent = `Classified as ${category}`;
  } catch (e) {
    button.querySelector(".ticket-meta").textContent = "Network error: " + e.message;
  } finally {
    setTimeout(() => { button.disabled = false; }, 800);
  }
}

document.querySelectorAll(".ticket").forEach((b) => {
  b.addEventListener("click", () => classifyTicket(b.dataset.ticket, b));
});

// ---- Helpers ----
function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
