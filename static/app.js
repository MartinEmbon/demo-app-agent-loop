/* ────────────────────────────────────────────────────────────
   AgentLoop demo — orchestration

   Manages a 3-step guided flow:
     Step 1: visitor asks → agent answers (probably wrong)
     Step 2: visitor corrects → AgentLoop stores memory
     Step 3: visitor asks again → agent uses memory, answers right

   State lives in this module + sessionStorage. The user_id we send
   to the backend scopes every visitor's memories to themselves.
   ──────────────────────────────────────────────────────────── */

// ────────────────────────────────────────────────────────────
// Session

const SESSION_KEY = "agentloop_demo_session";

function getOrCreateSession() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = "demo_" + Math.random().toString(36).slice(2, 10);
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function resetSession() {
  sessionStorage.removeItem(SESSION_KEY);
  return getOrCreateSession();
}

let sessionId = getOrCreateSession();
document.getElementById("session-id").textContent = sessionId;

// In-memory state of the current loop iteration.
// We hold the question/answer between steps so step 2 can reference
// what the agent said in step 1, and step 3 can re-ask the same thing.
const state = {
  question: null,
  wrongAnswer: null,
  correction: null,
};

// ────────────────────────────────────────────────────────────
// Step locking

function unlockStep(n) {
  const el = document.getElementById(`step-${n}`);
  if (!el.classList.contains("locked")) return;
  el.classList.remove("locked");
  el.classList.add("unlocked-anim");
  // Smooth-scroll the unlocked step into view so the visitor sees it.
  // Slight delay so the unlock animation starts before the scroll.
  setTimeout(() => {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 200);
}

function lockStepsFrom(n) {
  for (let i = n; i <= 3; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.add("locked");
    el.classList.remove("unlocked-anim");
    const output = document.getElementById(`step${i}-output`);
    if (output) output.hidden = true;
  }
}

// ────────────────────────────────────────────────────────────
// Step 1 — Ask

const step1Input = document.getElementById("step1-input");
const step1Send = document.getElementById("step1-send");
const step1Output = document.getElementById("step1-output");
const step1Question = document.getElementById("step1-question");
const step1Answer = document.getElementById("step1-answer");
const step1Badge = document.getElementById("step1-badge");

async function askStep1(question) {
  question = question.trim();
  if (!question) return;

  // Lock UI during request
  setStep1Disabled(true);
  step1Send.textContent = "Asking…";

  // Pre-render the question + loading state
  step1Question.textContent = question;
  step1Answer.textContent = "Thinking…";
  step1Badge.textContent = "—";
  step1Output.hidden = false;

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, user_id: sessionId }),
    });

    if (!res.ok) {
      const err = await res.text();
      step1Answer.textContent = `Error: ${err}`;
      step1Badge.textContent = "—";
      return;
    }

    const data = await res.json();
    step1Answer.textContent = data.answer;
    step1Badge.textContent =
      data.memories_used === 0
        ? "0 memories used"
        : `${data.memories_used} ${data.memories_used === 1 ? "memory" : "memories"} used`;

    // Save state for steps 2 & 3
    state.question = question;
    state.wrongAnswer = data.answer;

    // Pre-fill step 3's input with the same question
    document.getElementById("step3-input").value = question;

    // Unlock step 2
    unlockStep(2);
  } catch (e) {
    step1Answer.textContent = `Network error: ${e.message}`;
    step1Badge.textContent = "—";
  } finally {
    setStep1Disabled(false);
    step1Send.innerHTML = 'Ask <span class="arrow">→</span>';
  }
}

function setStep1Disabled(disabled) {
  step1Send.disabled = disabled;
  step1Input.disabled = disabled;
  document.querySelectorAll(".example").forEach((b) => (b.disabled = disabled));
}

step1Send.addEventListener("click", () => askStep1(step1Input.value));
step1Input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") askStep1(step1Input.value);
});
document.querySelectorAll(".example").forEach((b) => {
  b.addEventListener("click", () => {
    step1Input.value = b.dataset.q;
    askStep1(b.dataset.q);
  });
});

// ────────────────────────────────────────────────────────────
// Step 2 — Correct

const step2Input = document.getElementById("step2-input");
const step2Send = document.getElementById("step2-send");
const step2Output = document.getElementById("step2-output");
const step2CorrectionText = document.getElementById("step2-correction-text");

// Enable the Save button only when the textarea has content
step2Input.addEventListener("input", () => {
  step2Send.disabled = step2Input.value.trim().length === 0;
});

async function submitCorrection() {
  const correction = step2Input.value.trim();
  if (!correction || !state.question || !state.wrongAnswer) return;

  step2Send.disabled = true;
  step2Input.disabled = true;
  step2Send.textContent = "Saving…";

  try {
    const res = await fetch("/api/correct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: state.question,
        agent_response: state.wrongAnswer,
        correction,
        user_id: sessionId,
      }),
    });

    if (!res.ok) {
      const err = await res.text();
      step2Send.innerHTML = 'Save correction <span class="arrow">→</span>';
      step2Send.disabled = false;
      step2Input.disabled = false;
      alert(`Couldn't save correction: ${err}`);
      return;
    }

    // Read the response so we can swap to the fresh user_id the backend
    // minted. From here on, /ask calls go against the new scope — only
    // this latest correction is reachable. If we corrected the same
    // question previously in this tab, that older memory is now orphaned
    // (still in the backend, just unreachable from here).
    try {
      const body = await res.json();
      if (body && body.new_user_id) {
        sessionId = body.new_user_id;
        sessionStorage.setItem(SESSION_KEY, sessionId);
        document.getElementById("session-id").textContent = sessionId;
      }
    } catch (_) {
      // Older backend without new_user_id — proceed with the same id.
    }

    // Success — render the confirmation and unlock step 3
    state.correction = correction;
    step2CorrectionText.textContent = correction;
    step2Output.hidden = false;

    // Restore the step 2 controls so they're ready for a future cycle
    // (e.g. after the visitor hits Reset). The button stays visually fine
    // because the output block now covers it, but the underlying state
    // needs to be clean for the next run.
    step2Send.innerHTML = 'Save correction <span class="arrow">→</span>';
    step2Input.disabled = false;

    // Enable the "Ask again" button in step 3
    document.getElementById("step3-send").disabled = false;
    unlockStep(3);
  } catch (e) {
    step2Send.disabled = false;
    step2Input.disabled = false;
    step2Send.innerHTML = 'Save correction <span class="arrow">→</span>';
    alert(`Network error: ${e.message}`);
  }
}

step2Send.addEventListener("click", submitCorrection);

// ────────────────────────────────────────────────────────────
// Step 3 — Ask again

const step3Send = document.getElementById("step3-send");
const step3Output = document.getElementById("step3-output");
const step3Question = document.getElementById("step3-question");
const step3Answer = document.getElementById("step3-answer");
const step3Badge = document.getElementById("step3-badge");
const celebration = document.getElementById("celebration");

async function askStep3() {
  if (!state.question) return;

  step3Send.disabled = true;
  step3Send.textContent = "Asking…";

  step3Question.textContent = state.question;
  step3Answer.textContent = "Thinking…";
  step3Badge.textContent = "—";
  step3Output.hidden = false;
  celebration.hidden = true;

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: state.question, user_id: sessionId }),
    });

    if (!res.ok) {
      const err = await res.text();
      step3Answer.textContent = `Error: ${err}`;
      step3Badge.textContent = "—";
      return;
    }

    const data = await res.json();
    step3Answer.textContent = data.answer;
    const n = data.memories_used;
    step3Badge.textContent =
      n === 0
        ? "0 memories used"
        : `${n} ${n === 1 ? "memory" : "memories"} used`;

    // If at least one memory was used, show the celebration callout.
    // (If somehow none was retrieved — embedding race, or the correction
    // wasn't similar enough to the question — skip the celebration so
    // we don't lie to the visitor.)
    if (n > 0) {
      celebration.hidden = false;
    }
  } catch (e) {
    step3Answer.textContent = `Network error: ${e.message}`;
    step3Badge.textContent = "—";
  } finally {
    step3Send.innerHTML = 'Ask again <span class="arrow">→</span>';
    step3Send.disabled = false;
  }
}

step3Send.addEventListener("click", askStep3);

// ────────────────────────────────────────────────────────────
// Reset

document.getElementById("reset-btn").addEventListener("click", () => {
  if (
    state.question &&
    !confirm("Reset the demo? Your current correction will be orphaned.")
  ) {
    return;
  }

  // Fresh session id (server-side memories from the old session stay
  // in the backend but are unreachable from this tab — they're tagged
  // "demo" and get cleaned up by a periodic job).
  sessionId = resetSession();
  document.getElementById("session-id").textContent = sessionId;

  // Clear local state
  state.question = null;
  state.wrongAnswer = null;
  state.correction = null;

  // Reset UI
  step1Input.value = "";
  step1Output.hidden = true;
  step2Input.value = "";
  step2Input.disabled = false;
  step2Send.disabled = true;
  step2Send.innerHTML = 'Save correction <span class="arrow">→</span>';
  step2Output.hidden = true;
  document.getElementById("step3-input").value = "";
  step3Send.disabled = true;
  step3Output.hidden = true;
  celebration.hidden = true;

  lockStepsFrom(2);

  // Scroll back to step 1
  document.getElementById("step-1").scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
});