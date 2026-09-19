const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="demo-token"]').content;
let state = null,
  busy = false,
  automatic = false;
// Voice: an active recognizer, a spoken task about to submit, and whether this run answers out loud.
let listening = null,
  pendingVoice = false,
  voiceRun = false,
  conversation = false, // "Keep listening": reopen the mic after each spoken answer.
  utterance = null; // Held so Chrome does not drop the utterance (and its onend) mid-sentence.
// The Website field holds a site named in an earlier task, not one the user typed.
let siteFromTask = false;
// A start page or website was picked by hand, so the next task opens it instead of continuing.
let freshStart = false;
// Wall-clock task time: from clicking Start demo until Jev reports done or blocked.
let startedAt = null,
  endedAt = null,
  clock = null,
  runId = 0;
// Steering test: recorded runs, the run already recorded, and whether "Run every wording" is going.
let steeringRuns = [],
  recordedRun = 0,
  sweeping = false;
function renderTotalTime() {
  const el = $("total-time");
  el.hidden = startedAt === null;
  if (startedAt === null) return;
  const seconds = (((endedAt ?? performance.now()) - startedAt) / 1000).toFixed(1);
  const done = endedAt !== null && state?.status === "done";
  el.classList.toggle("finished", done);
  el.textContent =
    endedAt === null ? `Total ${seconds} s` : done ? `Finished in ${seconds} s` : `Stopped after ${seconds} s`;
}
function startClock() {
  startedAt = performance.now();
  endedAt = null;
  clearInterval(clock);
  clock = setInterval(renderTotalTime, 100);
  renderTotalTime();
}
function stopClock(finished) {
  clearInterval(clock);
  clock = null;
  if (finished) endedAt = performance.now();
  else startedAt = endedAt = null;
  renderTotalTime();
}
const goals = {
  flights: 'Find one-way flights from Zurich to London on September 20, 2026, for one adult in economy. Stop when matching flight options are visible. Do not select or book a flight.',
  travel: 'Find a Design stay in Lisbon with Free cancellation and open Casa Flora.',
  research:
    "Open the article about using finite choices to control browser agents.",
  steering:
    "Open the article about using finite choices to control browser agents.",
  search: "",
  custom: "",
};
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const percent = (value) => `${(value * 100).toFixed(value < 0.01 ? 1 : 0)}%`;
async function call(name, body = {}) {
  const response = await fetch(`/api/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Demo-Token": token },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "Request failed");
  state = data;
  render();
  return data;
}
function controls() {
  const live = state?.page && !["done", "blocked"].includes(state.status);
  $("start").disabled = busy;
  $("mic").disabled = busy && !conversation; // Stays clickable mid-run so you can end the conversation.
  $("scenario").disabled = busy;
  $("goal").disabled = busy;
  for (const id of ["custom-url", "decoy", "sweep", "steering-clear"]) $(id).disabled = busy || sweeping;
  $("choose").disabled = busy || !live;
  $("execute").disabled = busy || !state?.decision || !live;
  $("auto").disabled = busy || !live;
  $("auto").hidden = automatic;
  $("stop").hidden = !automatic;
  $("download").disabled = !state?.history?.length;
}
async function perform(fn, label) {
  if (busy) return;
  busy = true;
  $("error").hidden = true;
  controls();
  $("status").textContent = label;
  try {
    await fn();
  } catch (error) {
    automatic = false;
    if (voiceRun) {
      answer(`Paused. ${error.message}`);
    }
    try {
      state = await fetch("/api/state").then((r) => r.json());
      render();
    } catch {
      /* Preserve the original failure if the server disconnected. */
    }
    $("error").textContent = error.message;
    $("error").hidden = false;
    $("status").textContent = "Paused · needs attention";
  } finally {
    busy = false;
    controls();
  }
}
function render() {
  if (!state) return;
  $("helper").textContent = `Text helper · ${state.text_model}`;
  $("plan").innerHTML = (state.plan || [])
    .map(
      (goal, i) =>
        `<div class="plan-step ${i === state.plan_index ? "current" : ""}"><span>${i < state.plan_index ? "✓" : i + 1}</span>${escape(goal)}</div>`,
    )
    .join("");
  const page = state.page,
    d =
      state.decision ||
      (state.status === "done" ? state.decisions?.at(-1) : null);
  const labels = {
    idle: "Ready to explore",
    ready: "Page observed · ready for a decision",
    predicted: "Choice ready · inspect or execute",
    done: "Jev reports complete · inspect the page",
    blocked: "Stopped · no supported next action",
  };
  $("status").textContent = labels[state.status] || state.status;
  if (clock !== null && ["done", "blocked"].includes(state.status)) {
    stopClock(true);
    recordSteering();
    if (voiceRun) {
      const n = Math.round((endedAt - startedAt) / 1000),
        seconds = `${n} second${n === 1 ? "" : "s"}`;
      answer(state.status === "done" ? `Done in ${seconds}.` : `I got stuck after ${seconds}.`);
    }
  }
  if (!page) {
    controls();
    return;
  }
  $("empty").hidden = true;
  $("screenshot").hidden = false;
  // A skipped frame (the background tab did not render in time) keeps the previous picture.
  if (page.screenshot) $("screenshot").src = `data:image/jpeg;base64,${page.screenshot}`;
  $("url").textContent = page.url;
  $("page-title").textContent = page.title;
  $("action-count").textContent = `${state.elements.length} elements`;
  const chosen = page.actions.find((a) => a.id === d?.choice);
  $("choice-title").textContent = d
    ? chosen?.label || d.choice
    : "Choose an action";
  $("latency").textContent = d ? `${d.latency_ms} ms` : "—";
  $("confidence").textContent = d?.target_confidence != null ? percent(d.target_confidence) : "—";
  $("completion").textContent = d ? d.operation : "—";
  $("ranking-note").textContent = d ? "Ranked by Jev" : "Unranked";
  const op = Object.entries(d?.operation_probabilities || {}).sort((a,b)=>b[1]-a[1]);
  $("operation-choices").innerHTML = op.map(([name,p]) =>
    `<span class="operation-choice ${name === d.operation ? 'best' : ''}">${escape(name)} <b>${percent(p)}</b></span>`).join('');
  const probability = e => d?.target_probabilities[e.index] ??
    Math.max(-1, ...(e.options || []).map(o=>d?.target_probabilities[o.index] ?? -1));
  const selectedIndex = d?.target?.split(':')[0];
  const elements = [...state.elements];
  if (d) elements.sort((a,b)=>probability(b)-probability(a));
  $("choices").innerHTML = elements.map(e => {
    const p = probability(e);
    return `<div class="choice ${selectedIndex === e.index ? 'best' : ''}" data-action="${escape(e.index)}"><span class="choice-id">[${escape(e.index)}]</span><div class="choice-label">${escape(e.label)}<small>${escape(e.role)} · ${escape(e.operations.join(' / '))}${e.value ? ' · '+escape(e.value) : ''}${e.checked !== undefined ? ' · checked '+escape(e.checked) : ''}</small>${p >= 0 ? `<div class="bar" style="--probability:${p*100}%"></div>` : ''}</div><span class="probability">${p >= 0 ? percent(p) : '—'}</span></div>`;
  }).join('');
  const targets = new Map();
  for (const a of page.actions) if (a.rect && !targets.has(a.node)) targets.set(a.node, a);
  $("targets").innerHTML = [...targets.values()].map((a,i) => {
    const index=String(i+1);
    return `<div class="target ${index === selectedIndex ? 'selected' : ''}" data-action="${index}" style="left:${100*a.rect.x/page.w}%;top:${100*a.rect.y/page.h}%;width:${100*a.rect.w/page.w}%;height:${100*a.rect.h/page.h}%"><span>${index}</span></div>`;
  }).join('');
  $("targets").hidden = !$("overlays").checked;
  $("history").innerHTML = state.history.length
    ? state.history
        .map(
          (h) =>
            `<div class="trace-row"><span class="number">${String(h.step).padStart(2, "0")}</span><div>${escape(h.action)}${h.text ? ` <b>“${escape(h.text)}”</b><small>${escape(h.text_helper)}</small>` : ""}</div><span class="time">${h.latency_ms} ms · ${percent(h.probability)}</span><span class="effect">${h.page_changed ? "Page changed" : "No change observed"}</span></div>`,
        )
        .join("")
    : '<p class="muted">Each executed action leaves an observed result.</p>';
  $("step-count").textContent = `${state.history.length} actions · ${(state.elapsed_ms / 1000).toFixed(2)} s`;
  $("model-state").textContent = JSON.stringify(
    d?.request || {
      goal: state.goal,
      url: page.url,
      text: page.text,
      actions: page.actions.map(({ rect, node, ...rest }) => rest),
    },
    null,
    2,
  );
  controls();
}
// A website named in the task ("open youtube.com"), since Jev itself cannot use the address bar.
function siteInTask(goal) {
  const match = /(?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,24}(?![a-z0-9-])(?:\/[^\s"'<>]*)?/i.exec(goal);
  return match ? match[0].replace(/[.,;:!?)]+$/, "") : null;
}
// Opens a fresh browser for the chosen scenario, then (optionally) runs it to the end.
async function startRun(autorun = $("autorun").checked) {
  automatic = false;
  if (busy) return;
  const site = siteInTask($("goal").value);
  // A follow-up continues in Jev's tab from where the last request ended ("subscribe to the channel"),
  // unless a different start was picked since. A site named in it opens in that same tab.
  const followUp = !freshStart && !!state?.page && ["search", "custom"].includes(state.scenario);
  // A website named in the task always wins over a leftover address from an earlier run.
  if (!followUp && site) {
    $("scenario").value = "custom";
    $("custom-url").value = site;
    siteFromTask = true;
  } else if (!followUp && siteFromTask) {
    // No site named: start from a web search, not the previous task's site.
    $("scenario").value = "search";
    siteFromTask = false;
  }
  scenarioOptions();
  // Only runs started by voice answer out loud; typed runs stay silent.
  voiceRun = pendingVoice;
  pendingVoice = false;
  startClock();
  let opened = false;
  await perform(async () => {
    try {
      if (followUp) await call("continue", { goal: $("goal").value, url: site || "" });
      else
        await call("reset", {
          scenario: $("scenario").value,
          goal: $("goal").value,
          url: $("custom-url").value,
          decoy: $("decoy").value,
        });
      opened = true;
      freshStart = false;
      runId++;
    } catch (error) {
      stopClock(false); // No task started, so there is nothing to time.
      throw error;
    }
  }, followUp ? "Continuing from this page…" : "Opening a fresh browser…");
  if (opened && autorun) await runAutomatically();
  // A spoken run that ended without done/blocked/error (paused, or out of steps) still answers.
  if (opened && autorun && voiceRun) answer("I stopped before finishing.");
}
$("task-form").addEventListener("submit", (event) => {
  event.preventDefault();
  startRun();
});
function scenarioOptions() {
  const scenario = $("scenario").value;
  $("custom-options").hidden = scenario !== "custom";
  $("steering-options").hidden = scenario !== "steering";
  $("steering-results").hidden = scenario !== "steering" && !steeringRuns.length;
  $("goal").placeholder =
    scenario === "custom"
      ? "Describe what Jev should do on this website"
      : scenario === "search"
        ? "Describe what Jev should find on the web"
        : "";
}
$("custom-url").addEventListener("input", () => {
  siteFromTask = false;
  freshStart = true;
});
$("scenario").addEventListener("change", () => {
  siteFromTask = false;
  freshStart = true;
  $("goal").value = goals[$("scenario").value];
  scenarioOptions();
  if ($("scenario").value === "custom") $("custom-url").focus();
});

// Steering test: which article Jev opened first, and where it ended, per decoy wording.
try {
  steeringRuns = JSON.parse(localStorage.getItem("steering-runs")) || [];
} catch {
  /* Results are a convenience; start empty if storage is unavailable. */
}
const wordingName = (value) => $("decoy").querySelector(`option[value="${value}"]`)?.textContent || value;
function articleAt(url) {
  const hash = /#(decoy|choices|latency|uncertainty)$/.exec(url || "")?.[1];
  return hash === "choices" ? "correct" : hash === "decoy" ? "decoy" : hash ? "other" : "none";
}
function recordSteering() {
  if (state?.scenario !== "steering" || !state.page || recordedRun === runId) return;
  recordedRun = runId;
  const opened = state.history.find((h) => articleAt(h.url) !== "none");
  steeringRuns.push({
    decoy: state.decoy,
    first: opened ? articleAt(opened.url) : "none",
    final: articleAt(state.page.url),
    confidence: opened?.probability ?? null,
    seconds: startedAt === null ? null : ((endedAt ?? performance.now()) - startedAt) / 1000,
    status: state.status,
  });
  try {
    localStorage.setItem("steering-runs", JSON.stringify(steeringRuns));
  } catch {
    /* Keep the in-page table even if storage is unavailable. */
  }
  renderSteering();
}
function renderSteering() {
  const labels = { correct: "Correct article", decoy: "Decoy", other: "Another article", none: "Nothing opened" };
  const outcome = (value) => `<span class="outcome ${value === "other" ? "none" : value}">${labels[value]}</span>`;
  $("steering-count").textContent = `${steeringRuns.length} run${steeringRuns.length === 1 ? "" : "s"}`;
  $("steering-rows").innerHTML = steeringRuns
    .map(
      (r, i) =>
        `<tr><td>${i + 1}</td><td>${escape(wordingName(r.decoy))}</td><td>${outcome(r.first)}</td><td>${outcome(r.final)}${
          ["done", "blocked"].includes(r.status) ? "" : "<small>unfinished</small>"
        }</td><td>${r.confidence == null ? "—" : percent(r.confidence)}</td><td>${
          r.seconds == null ? "—" : r.seconds.toFixed(1) + " s"
        }</td></tr>`,
    )
    .join("");
  scenarioOptions();
}
$("steering-clear").addEventListener("click", () => {
  steeringRuns = [];
  try {
    localStorage.removeItem("steering-runs");
  } catch {
    /* Nothing stored. */
  }
  renderSteering();
});
$("sweep").addEventListener("click", async () => {
  if (busy) return;
  sweeping = true;
  for (const option of $("decoy").options) {
    if (!sweeping) break;
    $("decoy").value = option.value;
    await startRun(true);
    recordSteering(); // Records unfinished runs too; finished ones were recorded already.
  }
  sweeping = false;
  controls();
});
renderSteering();
$("choose").addEventListener("click", () =>
  perform(() => call("predict"), "Jev is comparing the actions…"),
);
$("execute").addEventListener("click", () =>
  perform(
    () => call("act", { fingerprint: state.page.fingerprint }),
    "Executing the choice…",
  ),
);
const runAutomatically = () =>
  perform(async () => {
    automatic = true;
    controls();
    for (let i = 0; i < state.max_steps * 2 && automatic && !interrupted; i++) {
      $("status").textContent = "Running…";
      if ($("pace").checked) {
        await call("predict");
        await new Promise(resolve => setTimeout(resolve, 450));
        if (!automatic || interrupted) break;
        await call("act", {fingerprint: state.page.fingerprint});
      } else {
        await call("tick");
      }
      if (["done", "blocked"].includes(state.status)) break;
    }
    automatic = false;
  }, "Running the browser…");
$("auto").addEventListener("click", runAutomatically);
// Voice: Chrome's built-in speech recognition fills the task, then starts the run.
// With "Keep listening" on, the mic stays open during runs too, so you can talk over a misunderstanding:
// speaking pauses Jev after its current step, then "stop" ends the task, anything else replaces it as a
// correction, and noise with no words lets it carry on. Click the mic off or say "stop listening" to end.
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const STOP_TASK = /^(stop|wait|cancel|pause|hold on|never ?mind|no)[.!]?$/i;
const END_CONVERSATION = /^(stop listening|that's all|that is all|goodbye|bye)[.!]?$/i;
let speaking = false,
  interrupted = null; // A run paused because you started talking: {voice} restores it if you said nothing.
function say(text, then = () => {}) {
  if (!window.speechSynthesis) return then();
  speechSynthesis.cancel();
  speaking = true;
  listening?.abort(); // The mic must not hear Jev's answer as your next request.
  utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  utterance.onend = utterance.onerror = () => {
    utterance = null;
    speaking = false;
    then();
  };
  speechSynthesis.speak(utterance);
}
function keepListening() {
  if (conversation && !speaking && !listening) listen();
}
// A step already sent to the browser finishes first; act on what you said once the run has let go.
function whenIdle(fn) {
  if (busy) setTimeout(() => whenIdle(fn), 100);
  else fn();
}
// Speaks a voice run's outcome, then reopens the mic if the conversation is still on.
function answer(text) {
  voiceRun = false;
  say(text, keepListening);
}
function micLabel() {
  $("mic").classList.toggle("listening", !!listening || conversation);
  $("mic").textContent = conversation
    ? "● Mic on · click to end"
    : listening
      ? "● Listening… click to stop"
      : "🎤 Speak";
}
function endConversation() {
  conversation = false;
  listening?.abort();
  micLabel();
  controls();
}
function listen() {
  const recognition = new Recognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  const previous = $("goal").value;
  let transcript = "",
    final = false,
    failed = false,
    dropped = false;
  recognition.onresult = (event) => {
    transcript = [...event.results].map((r) => r[0].transcript).join("").trim();
    final = event.results[event.results.length - 1].isFinal;
    if (!busy && !interrupted) {
      $("goal").value = transcript;
      return;
    }
    // Talking over a run pauses it at the first recognised word; waiting for the full sentence lets a
    // misunderstood task run on for seconds.
    if (transcript && !interrupted) {
      interrupted = { voice: voiceRun };
      automatic = voiceRun = false;
    }
    if (interrupted) $("status").textContent = `Heard “${transcript}” · pausing…`;
  };
  recognition.onerror = (event) => {
    if (event.error === "aborted") dropped = true;
    if (event.error === "no-speech" || event.error === "aborted") return;
    failed = true;
    $("error").textContent =
      event.error === "not-allowed"
        ? "Microphone access is blocked. Allow it in the address bar, then try again."
        : `Speech recognition failed: ${event.error}`;
    $("error").hidden = false;
  };
  recognition.onend = () => {
    if (listening === recognition) listening = null;
    if (failed) conversation = false;
    const heard = final && !dropped ? transcript : "";
    const paused = interrupted;
    if (!paused && !busy && !heard) $("goal").value = previous;
    // With no run to stop, a plain "stop" still ends the conversation, as before.
    if (END_CONVERSATION.test(heard) || (!paused && /^stop[.!]?$/i.test(heard))) {
      if (!paused) $("goal").value = previous;
      endConversation();
      return whenIdle(() => {
        interrupted = null;
        if (paused) stopClock(true);
        say("Okay, I stopped listening.");
      });
    }
    micLabel();
    if (paused) {
      whenIdle(() => {
        interrupted = null;
        if (STOP_TASK.test(heard)) {
          stopClock(true);
          $("status").textContent = "Stopped · you asked Jev to stop";
          answer("Okay, I stopped.");
        } else if (heard) {
          // A correction becomes the next request in the same tab; the paused one is kept as "not finished".
          $("goal").value = heard;
          pendingVoice = true;
          $("task-form").requestSubmit();
        } else {
          voiceRun = paused.voice;
          runAutomatically();
        }
      });
    } else if (heard) {
      pendingVoice = true;
      $("task-form").requestSubmit();
    }
    // Chrome ends recognition after a pause in speech; reopen it, during runs too, while the conversation is on.
    setTimeout(keepListening, 250);
  };
  $("error").hidden = true;
  listening = recognition;
  micLabel();
  recognition.start();
}
$("mic").hidden = $("keep-listening-control").hidden = !Recognition;
$("mic").addEventListener("click", () => {
  if (conversation) return endConversation();
  if (listening) return listening.stop(); // Without "Keep listening": stop and submit what was heard.
  if (busy) return;
  conversation = $("keep-listening").checked;
  listen();
});
$("stop").addEventListener("click", () => {
  automatic = false;
  sweeping = false;
  $("status").textContent = "Pausing after the current request…";
  controls();
});
$("overlays").addEventListener("change", () => {
  $("targets").hidden = !$("overlays").checked;
});
$("choices").addEventListener("pointerover", (event) => {
  const id = event.target.closest("[data-action]")?.dataset.action;
  document
    .querySelectorAll(".target")
    .forEach((t) =>
      t.classList.toggle(
        "selected",
        t.dataset.action === id || t.dataset.action === state?.decision?.target?.split(':')[0],
      ),
    );
});
$("choices").addEventListener("pointerleave", () =>
  document
    .querySelectorAll(".target")
    .forEach((t) =>
      t.classList.toggle(
        "selected",
        t.dataset.action === state?.decision?.target?.split(':')[0],
      ),
    ),
);
$("download").addEventListener("click", () => {
  const { page, ...rest } = state;
  const blob = new Blob(
    [
      JSON.stringify(
        { ...rest, page: { ...page, screenshot: undefined } },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "typesafe-browser-trace.json";
  a.click();
  URL.revokeObjectURL(url);
});
fetch("/api/state")
  .then((r) => r.json())
  .then((s) => {
    state = s;
    render();
  })
  .catch(() => {
    $("status").textContent = "Cannot reach local demo server";
  });
