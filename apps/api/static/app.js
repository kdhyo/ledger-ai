const logEl = document.getElementById("log");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("message-input");
const statusEl = document.getElementById("status");
const confirmEl = document.getElementById("confirm");
const confirmTextEl = document.getElementById("confirm-text");
const confirmYesEl = document.getElementById("confirm-yes");
const confirmNoEl = document.getElementById("confirm-no");

let pendingConfirm = null;
let isComposing = false;

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  row.appendChild(bubble);
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text) {
  statusEl.textContent = text;
}

function renderConfirm(confirm) {
  pendingConfirm = confirm;
  if (!confirm) {
    confirmEl.classList.add("hidden");
    confirmTextEl.textContent = "";
    return;
  }

  confirmEl.classList.remove("hidden");
  confirmTextEl.textContent = confirm.prompt || "Pending confirmation";
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json();
}

async function sendMessage(text) {
  setStatus("Sending...");
  addMessage("user", text);

  try {
    const data = await postJson("/chat", { message: text });
    addMessage("assistant", data.reply || "");
    renderConfirm(data.pending_confirm);
  } catch (error) {
    addMessage("assistant", "Error: could not reach server.");
  } finally {
    setStatus("Ready");
  }
}

async function confirmAction(decision) {
  if (!pendingConfirm) {
    return;
  }
  setStatus("Sending...");
  try {
    const data = await postJson("/confirm", {
      token: pendingConfirm.token,
      decision,
    });
    addMessage("assistant", data.reply || "");
    renderConfirm(data.pending_confirm);
  } catch (error) {
    addMessage("assistant", "Error: confirmation failed.");
  } finally {
    setStatus("Ready");
  }
}

formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  if (isComposing) {
    return;
  }
  const text = inputEl.value.trim();
  if (!text) {
    return;
  }
  inputEl.value = "";
  sendMessage(text);
});

confirmYesEl.addEventListener("click", () => confirmAction("yes"));
confirmNoEl.addEventListener("click", () => confirmAction("no"));

inputEl.addEventListener("compositionstart", () => {
  isComposing = true;
});

inputEl.addEventListener("compositionend", () => {
  isComposing = false;
});
