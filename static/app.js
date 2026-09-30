const $ = (sel) => document.querySelector(sel);
const MIN_SECONDS = 0.4;
const TAIL_MS = 250; // keep recording briefly after release so the last word isn't cut

const state = {
  sessionId: null,
  selectedTopic: null,
  busy: false,
  pressing: false,
  recorder: new PushToTalkRecorder(),
};

// ---------- helpers ----------
async function api(path, options = {}) {
  const resp = await fetch(path, options);
  let data = null;
  try { data = await resp.json(); } catch { /* non-JSON */ }
  if (!resp.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${resp.status})`);
  }
  return data;
}

const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setHint(text, kind = "") {
  const hint = $("#hint");
  hint.textContent = text;
  hint.className = `hint ${kind || "muted"}`;
}

function resetHint() {
  const hint = $("#hint");
  hint.className = "hint muted";
  hint.innerHTML = "Konuşmak için düğmeyi basılı tut ya da <kbd>Space</kbd> tuşunu basılı tut.";
}

function setBusy(busy) {
  state.busy = busy;
  $("#talk").disabled = busy;
  $("#text-form button").disabled = busy;
  $("#finish").disabled = busy;
}

function scrollChat() {
  const chat = $("#chat");
  chat.scrollTop = chat.scrollHeight;
}

// ---------- rendering ----------
function addTeacher(turn) {
  const msg = el("div", "msg teacher");
  msg.append(el("div", "who", "Teacher"), el("p", "", turn.reply));
  if (turn.vocabulary && turn.vocabulary.length) {
    const vocab = el("div", "vocab");
    for (const v of turn.vocabulary) {
      const item = el("div", "vocab-item");
      item.append(el("strong", "", v.word), el("span", "", ` · ${v.meaning}`));
      if (v.example) item.append(el("em", "", v.example));
      vocab.append(item);
    }
    msg.append(vocab);
  }
  $("#chat").append(msg);
  scrollChat();
}

function addLearner(text) {
  const msg = el("div", "msg learner");
  msg.append(el("div", "who", "You"), el("p", "", text));
  $("#chat").append(msg);
  scrollChat();
  return msg;
}

function addFeedback(learnerMsg, turn) {
  const hasCorrections = turn.corrections && turn.corrections.length;
  if (!hasCorrections && !turn.better_version) {
    learnerMsg.append(el("div", "feedback ok", "✓ Hata yok"));
    return;
  }
  const box = el("div", "feedback");
  for (const c of turn.corrections || []) {
    const row = el("div", "correction");
    const pair = el("div", "pair");
    pair.append(el("del", "", c.original), el("span", "arrow", "→"), el("ins", "", c.corrected));
    row.append(pair);
    if (c.explanation) row.append(el("div", "why", c.explanation));
    box.append(row);
  }
  if (turn.better_version) {
    const better = el("div", "better");
    better.append(el("span", "label", "Daha doğal: "), el("span", "", turn.better_version));
    box.append(better);
  }
  learnerMsg.append(box);
  scrollChat();
}

function addThinking() {
  const msg = el("div", "msg teacher thinking");
  msg.append(el("div", "who", "Teacher"), el("p", "dots", "düşünüyor"));
  $("#chat").append(msg);
  scrollChat();
  return msg;
}

function addError(text) {
  $("#chat").append(el("div", "msg-error", text));
  scrollChat();
}

// ---------- setup ----------
async function loadConfig() {
  const cfg = await api("/api/config");
  const wrap = $("#topics");
  for (const t of cfg.topics) {
    const btn = el("button", "topic");
    btn.type = "button";
    btn.dataset.id = t.id;
    btn.append(el("strong", "", t.title_tr), el("span", "", t.title));
    btn.addEventListener("click", () => {
      state.selectedTopic = t.id;
      $("#custom-topic").value = "";
      document.querySelectorAll(".topic").forEach((b) => b.classList.toggle("selected", b === btn));
    });
    wrap.append(btn);
  }
  $("#status-llm").title = `Dil modeli: ${cfg.model}`;
}

async function checkHealth() {
  try {
    const h = await api("/api/health");
    for (const [key, id] of [["llm", "#status-llm"], ["stt", "#status-stt"]]) {
      const chip = $(id);
      chip.classList.toggle("ok", h[key].ok);
      chip.classList.toggle("bad", !h[key].ok);
      chip.title = h[key].detail;
    }
  } catch { /* server down: chips stay neutral */ }
}

function restorePrefs() {
  try {
    const prefs = JSON.parse(localStorage.getItem("tutor-prefs") || "{}");
    for (const id of ["level", "correction-mode", "explain-lang"]) if (prefs[id]) $("#" + id).value = prefs[id];
    $("#review-transcript").checked = !!prefs.review;
  } catch { /* storage unavailable */ }
}

function savePrefs() {
  try {
    localStorage.setItem("tutor-prefs", JSON.stringify({
      level: $("#level").value,
      "correction-mode": $("#correction-mode").value,
      "explain-lang": $("#explain-lang").value,
      review: $("#review-transcript").checked,
    }));
  } catch { /* storage unavailable */ }
}

$("#custom-topic").addEventListener("input", () => {
  if ($("#custom-topic").value.trim()) {
    state.selectedTopic = null;
    document.querySelectorAll(".topic").forEach((b) => b.classList.remove("selected"));
  }
});

$("#start").addEventListener("click", async () => {
  const errorBox = $("#setup-error");
  errorBox.hidden = true;
  const custom = $("#custom-topic").value.trim();
  if (!custom && !state.selectedTopic) {
    errorBox.textContent = "Bir konu seç ya da kendi konunu yaz.";
    errorBox.hidden = false;
    return;
  }
  savePrefs();
  const startBtn = $("#start");
  startBtn.disabled = true;
  startBtn.textContent = "Öğretmen hazırlanıyor…";
  try {
    const res = await postJSON("/api/sessions", {
      topic_id: state.selectedTopic,
      custom_topic: custom || null,
      level: $("#level").value,
      correction_mode: $("#correction-mode").value,
      explain_lang: $("#explain-lang").value,
    });
    state.sessionId = res.session_id;
    $("#lesson-topic").textContent = res.topic;
    $("#chat").innerHTML = "";
    $("#setup").hidden = true;
    $("#summary").hidden = true;
    $("#lesson").hidden = false;
    resetHint();
    addTeacher(res.turn);
    state.recorder.ensureStream().catch(() => setHint("Mikrofon izni verilmedi. Yazarak da devam edebilirsin.", "error"));
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  } finally {
    startBtn.disabled = false;
    startBtn.textContent = "Derse başla";
  }
});

// ---------- conversation ----------
async function sendText(text) {
  text = text.trim();
  if (!text || state.busy) return;
  setBusy(true);
  $("#text-input").value = "";
  const learnerMsg = addLearner(text);
  const thinking = addThinking();
  try {
    const turn = await postJSON(`/api/sessions/${state.sessionId}/messages`, { text });
    thinking.remove();
    addFeedback(learnerMsg, turn);
    addTeacher(turn);
  } catch (err) {
    thinking.remove();
    learnerMsg.classList.add("failed");
    addError(err.message);
    $("#text-input").value = text;
  } finally {
    setBusy(false);
    resetHint();
  }
}

$("#text-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendText($("#text-input").value);
});

async function pressStart() {
  if (state.busy || state.pressing || !state.sessionId) return;
  state.pressing = true;
  try {
    await state.recorder.start();
    if (!state.pressing) { // released while the mic was starting up
      state.recorder.stop().catch(() => {});
      return;
    }
    $("#talk").classList.add("recording");
    setHint("Dinliyorum… bırakınca gönderilecek.", "live");
  } catch {
    state.pressing = false;
    setHint("Mikrofona erişilemedi. Tarayıcı iznini kontrol et.", "error");
  }
}

async function pressEnd() {
  if (!state.pressing) return;
  state.pressing = false;
  if (!state.recorder.isRecording) return;
  setBusy(true); // blocks a new press while the tail is still being recorded
  await new Promise((r) => setTimeout(r, TAIL_MS));
  $("#talk").classList.remove("recording");
  let text = "";
  try {
    const { wav, seconds } = await state.recorder.stop();
    if (seconds < MIN_SECONDS) {
      setHint("Çok kısa oldu. Konuşurken düğmeyi basılı tut.", "error");
      return;
    }
    setHint("Yazıya dökülüyor…", "live");
    const form = new FormData();
    form.append("audio", wav, "speech.wav");
    text = (await api("/api/transcribe", { method: "POST", body: form })).text;
    if (!text) {
      setHint("Bir şey duyamadım, tekrar dener misin?", "error");
      return;
    }
  } catch (err) {
    setHint(err.message, "error");
    return;
  } finally {
    setBusy(false);
  }
  if ($("#review-transcript").checked) {
    $("#text-input").value = text;
    $("#text-input").focus();
    setHint("Metni kontrol et, gerekirse düzelt ve Enter'a bas.", "live");
  } else {
    sendText(text);
  }
}

const talk = $("#talk");
talk.addEventListener("pointerdown", (e) => { e.preventDefault(); talk.setPointerCapture(e.pointerId); pressStart(); });
talk.addEventListener("pointerup", pressEnd);
talk.addEventListener("pointercancel", pressEnd);
talk.addEventListener("contextmenu", (e) => e.preventDefault());

const typing = () => ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat || typing() || $("#lesson").hidden) return;
  e.preventDefault();
  pressStart();
});
document.addEventListener("keyup", (e) => {
  if (e.code !== "Space" || typing() || $("#lesson").hidden) return;
  e.preventDefault();
  pressEnd();
});

// ---------- summary ----------
function list(title, items) {
  const box = el("div", "summary-block");
  box.append(el("h3", "", title));
  const ul = el("ul");
  for (const item of items) ul.append(el("li", "", item));
  box.append(ul);
  return box;
}

$("#finish").addEventListener("click", async () => {
  if (state.busy) return;
  setBusy(true);
  setHint("Ders değerlendiriliyor…", "live");
  try {
    const s = await postJSON(`/api/sessions/${state.sessionId}/summary`);
    const panel = $("#summary");
    panel.innerHTML = "";
    panel.append(el("h2", "", "Ders özeti"), el("p", "overall", s.overall_feedback));
    if (s.strengths.length) panel.append(list("İyi gidenler", s.strengths));
    if (s.common_mistakes.length) panel.append(list("Tekrarlayan hatalar", s.common_mistakes));
    if (s.next_steps.length) panel.append(list("Sonraki adımlar", s.next_steps));
    if (s.vocabulary.length) {
      panel.append(list("Kelimeler", s.vocabulary.map((v) => `${v.word}: ${v.meaning}`)));
    }
    const again = el("button", "primary", "Yeni ders");
    again.addEventListener("click", newLesson);
    panel.append(again);
    $("#lesson").hidden = true;
    panel.hidden = false;
  } catch (err) {
    setHint(err.message, "error");
  } finally {
    setBusy(false);
  }
});

function newLesson() {
  state.sessionId = null;
  $("#lesson").hidden = true;
  $("#summary").hidden = true;
  $("#setup").hidden = false;
  checkHealth();
}
$("#new-lesson").addEventListener("click", newLesson);

// ---------- boot ----------
restorePrefs();
loadConfig().catch((err) => {
  $("#setup-error").textContent = `Sunucuya ulaşılamadı: ${err.message}`;
  $("#setup-error").hidden = false;
});
checkHealth();
