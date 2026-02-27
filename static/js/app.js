/**
 * Sight Words Learning App
 * Lesson flow:
 *   Phase 0 - Demo: app reads sentence 1 aloud (OpenAI TTS), word-by-word highlighting
 *   Phase 1 - Practice: student reads sentence 2; then click-to-identify the sight word
 *   Phase 2 - Test word 1 from sentence 2
 *   Phase 3 - Test word 2 from sentence 2
 *   Complete screen
 */

"use strict";

// State
let lesson = null;          // data from /api/generate-lesson
let phase = 0;              // 0-3
let testQueue = [];         // [ { word, isSightWord } ]
let currentTest = null;
let roundResults = [];      // { word, correct }
let currentStudentId = null;  // active student id (integer)
let lastSightWord = "";     // last lesson's sight word -- avoid repeating
let sessionWords = new Set(); // sight words shown this session -- avoid same-session duplicates

// DOM refs
const startScreen    = document.getElementById("start-screen");
const pinScreen      = document.getElementById("pin-screen");
const lessonScreen   = document.getElementById("lesson-screen");
const completeScreen = document.getElementById("complete-screen");
const sightWordDisplay = document.getElementById("sight-word-display");
const sentenceEl     = document.getElementById("sentence-text");
const instructionEl  = document.getElementById("instruction-area");
const feedbackEl     = document.getElementById("feedback");
const btnReplay      = document.getElementById("btn-replay");
const btnNext        = document.getElementById("btn-next");
const phaseLabel     = document.getElementById("phase-label");
const roundSummary   = document.getElementById("round-summary");
const btnStart       = document.getElementById("btn-start");
const btnAgain       = document.getElementById("btn-again");
const dots           = [0,1,2,3].map(i => document.getElementById("dot-" + i));

// Student UI refs
const studentSelect    = document.getElementById("student-select");
const btnAddStudent    = document.getElementById("btn-add-student");
const newStudentForm   = document.getElementById("new-student-form");
const newStudentName   = document.getElementById("new-student-name");
const newStudentPin    = document.getElementById("new-student-pin");
const btnSaveStudent   = document.getElementById("btn-save-student");
const btnCancelStudent = document.getElementById("btn-cancel-student");

// PIN screen refs
const pinStudentName = document.getElementById("pin-student-name");
const pinDots        = document.querySelectorAll(".pin-dot");
const pinError       = document.getElementById("pin-error");
const pinOkBtn       = document.getElementById("pin-ok");
const pinClearBtn    = document.getElementById("pin-clear");
const btnPinBack     = document.getElementById("btn-pin-back");
let pinBuffer = "";

function updatePinDots() {
  pinDots.forEach((dot, i) => {
    dot.classList.toggle("filled", i < pinBuffer.length);
  });
}

document.querySelectorAll(".pin-key[data-digit]").forEach(btn => {
  btn.addEventListener("click", () => {
    if (pinBuffer.length < 8) {
      pinBuffer += btn.dataset.digit;
      updatePinDots();
    }
  });
});

if (pinClearBtn) {
  pinClearBtn.addEventListener("click", () => {
    pinBuffer = pinBuffer.slice(0, -1);
    updatePinDots();
  });
}

if (btnPinBack) {
  btnPinBack.addEventListener("click", () => {
    pinBuffer = "";
    updatePinDots();
    showScreen(startScreen);
  });
}

if (pinOkBtn) {
  pinOkBtn.addEventListener("click", async () => {
    const sid = getStudentId();
    const res = await fetch(`/api/students/${sid}/verify-pin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pinBuffer }),
    });
    if (res.ok) {
      pinError.classList.add("hidden");
      pinBuffer = "";
      updatePinDots();
      loadLesson(null);
    } else {
      pinError.classList.remove("hidden");
      pinBuffer = "";
      updatePinDots();
    }
  });
}

// Student helpers
function getStudentId() {
  const val = studentSelect && studentSelect.value;
  return val ? parseInt(val, 10) : 1;
}

if (btnAddStudent) {
  btnAddStudent.addEventListener("click", () => {
    newStudentForm.classList.remove("hidden");
    newStudentName.focus();
  });
}

if (btnCancelStudent) {
  btnCancelStudent.addEventListener("click", () => {
    newStudentForm.classList.add("hidden");
    newStudentName.value = "";
    if (newStudentPin) newStudentPin.value = "";
  });
}

if (btnSaveStudent) {
  btnSaveStudent.addEventListener("click", async () => {
    const name = newStudentName.value.trim();
    if (!name) return;
    const pin = newStudentPin ? newStudentPin.value.trim() : "";
    const res = await fetch("/api/students", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, pin: pin || null }),
    });
    if (res.ok) {
      const student = await res.json();
      const opt = document.createElement("option");
      opt.value = student.id;
      opt.textContent = student.name;
      opt.dataset.hasPin = student.has_pin ? "true" : "false";
      studentSelect.appendChild(opt);
      studentSelect.value = student.id;
      newStudentForm.classList.add("hidden");
      newStudentName.value = "";
      if (newStudentPin) newStudentPin.value = "";
    } else {
      const err = await res.json();
      alert(err.error || "Could not save student.");
    }
  });
}

// OpenAI TTS
const ttsAudio = document.getElementById("tts-audio");
const audioPendingEl = document.getElementById("audio-pending");
let ttsObjectUrl = null;
const ttsCache = new Map(); // text -> Blob (avoids repeated round-trips for frequent phrases)

function showAudioPending() {
  if (!audioPendingEl) return;
  audioPendingEl.classList.remove("hidden", "is-playing", "is-done");
}
function showAudioPlaying() {
  if (!audioPendingEl) return;
  audioPendingEl.classList.remove("hidden", "is-done");
  audioPendingEl.classList.add("is-playing");
}
function hideAudioPending() {
  if (!audioPendingEl) return;
  audioPendingEl.classList.remove("is-playing");
  audioPendingEl.classList.add("is-done");
  setTimeout(() => {
    audioPendingEl.classList.add("hidden");
    audioPendingEl.classList.remove("is-done");
  }, 1200);
}
function resetAudioPending() {
  if (!audioPendingEl) return;
  audioPendingEl.classList.add("hidden");
  audioPendingEl.classList.remove("is-playing", "is-done");
}

async function fetchTtsBlobCached(text, mode = "sentence") {
  const cacheKey = mode === "word" ? `word:${text}` : text;
  if (ttsCache.has(cacheKey)) return ttsCache.get(cacheKey);
  const res = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, mode }),
  });
  if (!res.ok) throw new Error("TTS request failed");
  const blob = await res.blob();
  ttsCache.set(cacheKey, blob);
  return blob;
}

async function speak(text, { onEnd = null, mode = "sentence" } = {}) {
  showAudioPending();
  try {
    const blob = await fetchTtsBlobCached(text, mode);
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(blob);
    ttsAudio.src = ttsObjectUrl;
    ttsAudio.onended = () => {
      hideAudioPending();
      if (onEnd) onEnd();
    };
    showAudioPlaying();
    await ttsAudio.play();
  } catch (err) {
    console.warn("TTS error:", err);
    resetAudioPending();
    if (onEnd) onEnd();
  }
}

/** Speak the word-test prompt: "Click the word" (cached) then the word in isolation. */
async function speakWordTest(word) {
  function waitForAudioEnd() {
    return new Promise(resolve => { ttsAudio.onended = resolve; });
  }
  try {
    // Pre-fetch both blobs in parallel for minimum latency
    const [promptBlob, wordBlob] = await Promise.all([
      fetchTtsBlobCached("Click the word"),
      fetchTtsBlobCached(word, "word"),
    ]);
    showAudioPending();
    // Play prompt
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(promptBlob);
    ttsAudio.src = ttsObjectUrl;
    showAudioPlaying();
    await ttsAudio.play();
    await waitForAudioEnd();
    // Play isolated word
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(wordBlob);
    ttsAudio.src = ttsObjectUrl;
    await ttsAudio.play();
    await waitForAudioEnd();
    hideAudioPending();
  } catch (err) {
    console.warn("TTS word-test error:", err);
    resetAudioPending();
  }
}

/** Pre-warm TTS cache for phrases that will definitely be needed. */
function prewarmTtsCache() {
  const phrases = [
    "Click the word",
    "Great job!",
    "Amazing! You got them all right!",
    "Good work! Keep practising!",
    "Now you read this sentence out loud!",
  ];
  phrases.forEach(p => fetchTtsBlobCached(p).catch(() => {}));
}

async function speakSentenceWithHighlight(sentence, tokenEls, onEnd) {
  showAudioPending();
  try {
    const blob = await fetchTtsBlobCached(sentence);
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(blob);
    ttsAudio.src = ttsObjectUrl;
    showAudioPlaying();

    ttsAudio.onloadedmetadata = () => {
      const durationMs = ttsAudio.duration * 1000;
      const words = sentence.split(/\s+/);
      const msPerWord = durationMs / words.length;
      let idx = 0;
      const iv = setInterval(() => {
        tokenEls.forEach(el => el.classList.remove("speaking"));
        if (idx < tokenEls.length) tokenEls[idx].classList.add("speaking");
        idx++;
        if (idx >= tokenEls.length) clearInterval(iv);
      }, msPerWord);
    };

    ttsAudio.onended = () => {
      tokenEls.forEach(el => el.classList.remove("speaking"));
      hideAudioPending();
      if (onEnd) onEnd();
    };

    await ttsAudio.play();
  } catch (err) {
    console.warn("TTS error:", err);
    resetAudioPending();
    // Fallback timing without audio
    const words = sentence.split(/\s+/);
    const msPerWord = 600;
    let idx = 0;
    const iv = setInterval(() => {
      tokenEls.forEach(el => el.classList.remove("speaking"));
      if (idx < tokenEls.length) tokenEls[idx].classList.add("speaking");
      idx++;
      if (idx >= tokenEls.length) {
        clearInterval(iv);
        tokenEls.forEach(el => el.classList.remove("speaking"));
        if (onEnd) onEnd();
      }
    }, msPerWord);
  }
}

// Build sentence tokens
function buildTokens(sentence, sightWord, clickable = false, highlightSightWord = true) {
  sentenceEl.innerHTML = "";
  const rawWords = sentence.split(/\s+/);
  const tokens = [];
  rawWords.forEach((raw, i) => {
    const span = document.createElement("span");
    span.classList.add("word-token");
    span.dataset.word = raw.replace(/[^a-zA-Z'-]/g, "").toLowerCase();
    span.textContent = (i < rawWords.length - 1) ? raw + " " : raw;

    if (highlightSightWord && span.dataset.word === sightWord.toLowerCase()) {
      span.classList.add("sight-word");
    }
    if (clickable) {
      span.classList.add("clickable");
      span.addEventListener("click", onWordClick);
    }
    sentenceEl.appendChild(span);
    tokens.push(span);
  });
  return tokens;
}

function getTokenEls() {
  return Array.from(sentenceEl.querySelectorAll(".word-token"));
}

// Phase management
function setPhase(p) {
  phase = p;
  dots.forEach((d, i) => {
    d.classList.remove("active", "done");
    if (i < p)  d.classList.add("done");
    if (i === p) d.classList.add("active");
  });
}

function setInstruction(html) {
  instructionEl.innerHTML = html;
}

function showFeedback(msg, type) {
  feedbackEl.textContent = msg;
  feedbackEl.className = "feedback " + type;
  feedbackEl.classList.remove("hidden");
  setTimeout(() => feedbackEl.classList.add("hidden"), 1800);
}

// Lesson flow
async function loadLesson(wordOverride) {
  showScreen(lessonScreen);
  setPhase(0);
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");
  sentenceEl.innerHTML = "...loading...";
  setInstruction("Getting your lesson ready...");

  currentStudentId = getStudentId();
  const body = {
    student_id: currentStudentId,
    previous_word: lastSightWord,
    seen_words: Array.from(sessionWords),
  };
  if (wordOverride) body.word = wordOverride;

  const res = await fetch("/api/generate-lesson", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  lesson = await res.json();
  roundResults = [];
  lastSightWord = lesson.sight_word;
  sessionWords.add(lesson.sight_word);

  sightWordDisplay.textContent = lesson.sight_word;
  phaseLabel.textContent = "Listen";

  // Build test queue: sight word first, then extra words
  testQueue = [
    { word: lesson.sight_word, isSightWord: true },
    ...lesson.test_words.map(w => ({ word: w, isSightWord: false }))
  ];

  runPhase0();
}

/** Phase 0: read demo sentence aloud with highlighting */
function runPhase0() {
  setPhase(0);
  phaseLabel.textContent = "Listen";
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");

  const tokens = buildTokens(lesson.demo_sentence, lesson.sight_word, false);
  setInstruction("Listen carefully! The <u>underlined word</u> is our new sight word.");

  speakSentenceWithHighlight(lesson.demo_sentence, tokens, () => {
    btnReplay.classList.remove("hidden");
    btnNext.classList.remove("hidden");
    btnNext.textContent = "I'm ready to read";
    btnNext.onclick = runPhase1;

    btnReplay.onclick = () => {
      speakSentenceWithHighlight(lesson.demo_sentence, getTokenEls(), () => {});
    };
  });
}

/** Phase 1: student reads practice sentence; then app prompts to click sight word */
function runPhase1() {
  setPhase(1);
  phaseLabel.textContent = "Read";
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");

  // Practice sentence: sight word NOT highlighted (student must find it themselves)
  buildTokens(lesson.practice_sentence, lesson.sight_word, false, false);
  const instructionText = "Now you read this sentence out loud!";
  setInstruction(instructionText);

  speak(instructionText, {
    onEnd: () => {
      btnNext.textContent = "I read it!";
      btnNext.classList.remove("hidden");
      btnNext.onclick = startTestQueue;
    }
  });
}

/** Begin clicking tests */
function startTestQueue() {
  btnNext.classList.add("hidden");
  btnReplay.classList.add("hidden");
  nextTest();
}

function nextTest() {
  if (testQueue.length === 0) {
    runComplete();
    return;
  }
  currentTest = testQueue.shift();
  const dotIdx = Math.min(4 - testQueue.length, 3);
  setPhase(dotIdx);
  phaseLabel.textContent = "Find it";

  // Practice sentence: sight word NOT highlighted during click tests either
  buildTokens(lesson.practice_sentence, lesson.sight_word, true, false);

  // Instruction text does NOT reveal the word — it's audio only
  setInstruction("🔊 Listen for the word to find…");
  speakWordTest(currentTest.word);
}

function onWordClick(e) {
  const clicked = e.currentTarget.dataset.word;
  const target  = currentTest.word.replace(/[^a-zA-Z'-]/g, "").toLowerCase();
  const correct = clicked === target;

  e.currentTarget.classList.add(correct ? "correct-flash" : "wrong-flash");
  setTimeout(() => {
    e.currentTarget.classList.remove("correct-flash", "wrong-flash");
  }, 600);

  fetch("/api/record-progress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word: currentTest.word, correct, student_id: currentStudentId })
  });

  roundResults.push({ word: currentTest.word, correct });

  if (correct) {
    showFeedback("Yes! Great job!", "correct");
    speak("Great job!");
  } else {
    showFeedback(`That's "${clicked}". The word was "${currentTest.word}".`, "wrong");
    speak(`Not quite. The word was ${currentTest.word}.`);
  }

  getTokenEls().forEach(el => {
    el.classList.remove("clickable");
    el.removeEventListener("click", onWordClick);
  });

  setTimeout(nextTest, 2000);
}

// Complete screen
function runComplete() {
  showScreen(completeScreen);
  const correct = roundResults.filter(r => r.correct).length;
  const total   = roundResults.length;
  let html = `<p class="score-line">You got <strong>${correct} out of ${total}</strong> right!</p><br>`;
  roundResults.forEach(r => {
    html += `<span>${r.correct ? "✅" : "❌"} <em>${r.word}</em></span><br>`;
  });
  roundSummary.innerHTML = html;
  speak(correct === total ? "Amazing! You got them all right!" : "Good work! Keep practising!");
}

// Screen helper
function showScreen(target) {
  [startScreen, pinScreen, lessonScreen, completeScreen].forEach(s => {
    s.classList.toggle("hidden", s !== target);
  });
}

// Event listeners
btnStart.addEventListener("click", () => {
  const selected = studentSelect && studentSelect.options[studentSelect.selectedIndex];
  const hasPin = selected && selected.dataset.hasPin === "true";
  // Reset session tracking for a fresh start
  sessionWords = new Set();
  lastSightWord = "";
  if (hasPin) {
    // Show PIN entry screen
    pinBuffer = "";
    updatePinDots();
    pinError.classList.add("hidden");
    pinStudentName.textContent = selected.textContent + " — Enter PIN";
    showScreen(pinScreen);
  } else {
    loadLesson(null);
  }
});
btnAgain.addEventListener("click", () => loadLesson(null));

// Pre-warm TTS cache for common fixed phrases on page load
prewarmTtsCache();
