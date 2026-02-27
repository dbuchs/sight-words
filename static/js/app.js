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

// DOM refs
const startScreen    = document.getElementById("start-screen");
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
const btnSaveStudent   = document.getElementById("btn-save-student");
const btnCancelStudent = document.getElementById("btn-cancel-student");

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
  });
}

if (btnSaveStudent) {
  btnSaveStudent.addEventListener("click", async () => {
    const name = newStudentName.value.trim();
    if (!name) return;
    const res = await fetch("/api/students", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (res.ok) {
      const student = await res.json();
      const opt = document.createElement("option");
      opt.value = student.id;
      opt.textContent = student.name;
      studentSelect.appendChild(opt);
      studentSelect.value = student.id;
      newStudentForm.classList.add("hidden");
      newStudentName.value = "";
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
  audioPendingEl && audioPendingEl.classList.remove("hidden");
}
function hideAudioPending() {
  audioPendingEl && audioPendingEl.classList.add("hidden");
}

async function fetchTtsBlobCached(text) {
  if (ttsCache.has(text)) return ttsCache.get(text);
  const res = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error("TTS request failed");
  const blob = await res.blob();
  ttsCache.set(text, blob);
  return blob;
}

async function speak(text, { onEnd = null } = {}) {
  showAudioPending();
  try {
    const blob = await fetchTtsBlobCached(text);
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(blob);
    ttsAudio.src = ttsObjectUrl;
    ttsAudio.onended = () => {
      hideAudioPending();
      if (onEnd) onEnd();
    };
    await ttsAudio.play();
  } catch (err) {
    console.warn("TTS error:", err);
    hideAudioPending();
    if (onEnd) onEnd();
  }
}

async function speakSentenceWithHighlight(sentence, tokenEls, onEnd) {
  showAudioPending();
  try {
    const blob = await fetchTtsBlobCached(sentence);
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(blob);
    ttsAudio.src = ttsObjectUrl;
    hideAudioPending();

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
      if (onEnd) onEnd();
    };

    await ttsAudio.play();
  } catch (err) {
    console.warn("TTS error:", err);
    hideAudioPending();
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
function buildTokens(sentence, sightWord, clickable = false) {
  sentenceEl.innerHTML = "";
  const rawWords = sentence.split(/\s+/);
  const tokens = [];
  rawWords.forEach((raw, i) => {
    const span = document.createElement("span");
    span.classList.add("word-token");
    span.dataset.word = raw.replace(/[^a-zA-Z'-]/g, "").toLowerCase();
    span.textContent = (i < rawWords.length - 1) ? raw + " " : raw;

    if (span.dataset.word === sightWord.toLowerCase()) {
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

  buildTokens(lesson.practice_sentence, lesson.sight_word, false);
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

  buildTokens(lesson.practice_sentence, lesson.sight_word, true);

  const cue = `Click on the word: <strong>"${currentTest.word}"</strong>`;
  setInstruction(cue);
  speak(`Click on the word: ${currentTest.word}`);
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
  [startScreen, lessonScreen, completeScreen].forEach(s => {
    s.classList.toggle("hidden", s !== target);
  });
}

// Event listeners
btnStart.addEventListener("click", () => loadLesson(null));
btnAgain.addEventListener("click", () => loadLesson(null));
