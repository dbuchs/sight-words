/**
 * Sight Words Learning App
 * Lesson flow:
 *   Phase 0 – Demo: app reads sentence 1 aloud, word-by-word highlighting
 *   Phase 1 – Practice: student reads sentence 2; then click-to-identify the sight word
 *   Phase 2 – Test word 1 from sentence 2
 *   Phase 3 – Test word 2 from sentence 2
 *   Complete screen
 */

"use strict";

// ── State ──────────────────────────────────────────────────────────────────
let lesson = null;          // data from /api/generate-lesson
let phase = 0;              // 0-3
let testQueue = [];         // [ { word, isSightWord } ]
let currentTest = null;
let roundResults = [];      // { word, correct }

// ── DOM refs ───────────────────────────────────────────────────────────────
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

// ── Web Speech API ─────────────────────────────────────────────────────────
const synth = window.speechSynthesis;

function speak(text, { rate = 0.85, onWord = null, onEnd = null } = {}) {
  synth.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = rate;
  utter.pitch = 1.1;

  // Try to pick a pleasant English voice
  const voices = synth.getVoices();
  const preferred = voices.find(v =>
    v.lang.startsWith("en") && (v.name.includes("Samantha") || v.name.includes("Google") || v.name.includes("Microsoft"))
  ) || voices.find(v => v.lang.startsWith("en")) || voices[0];
  if (preferred) utter.voice = preferred;

  if (onWord) utter.addEventListener("boundary", onWord);
  if (onEnd)  utter.addEventListener("end", onEnd);
  synth.speak(utter);
}

function speakSentenceWithHighlight(sentence, tokenEls, onEnd) {
  // Some browsers don't fire boundary events; we fall back to timing.
  let boundaryFired = false;

  function highlightWord(idx) {
    tokenEls.forEach(el => el.classList.remove("speaking"));
    if (idx < tokenEls.length) tokenEls[idx].classList.add("speaking");
  }

  speak(sentence, {
    onWord: (e) => {
      if (e.name !== "word") return;
      boundaryFired = true;
      // Find which token index corresponds to this char offset
      let charCount = 0;
      const rawWords = sentence.split(/\s+/);
      for (let i = 0; i < rawWords.length; i++) {
        if (e.charIndex >= charCount && e.charIndex < charCount + rawWords[i].length) {
          highlightWord(i);
          break;
        }
        charCount += rawWords[i].length + 1;
      }
    },
    onEnd: () => {
      tokenEls.forEach(el => el.classList.remove("speaking"));
      if (onEnd) onEnd();
    }
  });

  // Fallback timer if boundary events never fire
  setTimeout(() => {
    if (!boundaryFired) {
      const msPerWord = (sentence.split(/\s+/).length > 0)
        ? Math.round(3200 / sentence.split(/\s+/).length)
        : 600;
      let idx = 0;
      const iv = setInterval(() => {
        highlightWord(idx++);
        if (idx >= tokenEls.length) clearInterval(iv);
      }, msPerWord);
    }
  }, 400);
}

// ── Build sentence tokens ──────────────────────────────────────────────────
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

// ── Phase management ───────────────────────────────────────────────────────
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

// ── Lesson flow ────────────────────────────────────────────────────────────
async function loadLesson(wordOverride) {
  showScreen(lessonScreen);
  setPhase(0);
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");
  sentenceEl.innerHTML = "…loading…";
  setInstruction("Getting your lesson ready…");

  const body = wordOverride ? JSON.stringify({ word: wordOverride }) : "{}";
  const res = await fetch("/api/generate-lesson", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body
  });
  lesson = await res.json();
  roundResults = [];

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
  setInstruction("🔊 Listen carefully! The <u>underlined word</u> is our new sight word.");

  // Small delay so student can see the sentence before it's read
  setTimeout(() => {
    speakSentenceWithHighlight(lesson.demo_sentence, tokens, () => {
      // After reading, show Replay + Next
      btnReplay.classList.remove("hidden");
      btnNext.classList.remove("hidden");
      btnNext.textContent = "I'm ready to read ▶";
      btnNext.onclick = runPhase1;

      btnReplay.onclick = () => {
        speakSentenceWithHighlight(lesson.demo_sentence, getTokenEls(), () => {});
      };
    });
  }, 600);
}

/** Phase 1: student reads practice sentence; then app prompts to click sight word */
function runPhase1() {
  setPhase(1);
  phaseLabel.textContent = "Read";
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");

  buildTokens(lesson.practice_sentence, lesson.sight_word, false);
  setInstruction("📖 Now you read this sentence out loud!");

  // Give 4 seconds for the student to read, then start testing
  btnNext.textContent = "I read it! ▶";
  btnNext.classList.remove("hidden");
  btnNext.onclick = startTestQueue;
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
  // Phase 1 = sight-word test, 2 = first extra word, 3 = second extra word
  const dotIdx = Math.min(4 - testQueue.length, 3);
  setPhase(dotIdx);
  phaseLabel.textContent = "Find it";

  // Rebuild tokens as clickable (keep sight-word underline visible)
  buildTokens(lesson.practice_sentence, lesson.sight_word, true);

  const cue = `👆 Click on the word: <strong>"${currentTest.word}"</strong>`;
  setInstruction(cue);
  speak(`Click on the word: ${currentTest.word}`, { rate: 0.8 });
}

function onWordClick(e) {
  const clicked = e.currentTarget.dataset.word;
  const target  = currentTest.word.replace(/[^a-zA-Z'-]/g, "").toLowerCase();
  const correct = clicked === target;

  // Visual feedback on the token
  e.currentTarget.classList.add(correct ? "correct-flash" : "wrong-flash");
  setTimeout(() => {
    e.currentTarget.classList.remove("correct-flash", "wrong-flash");
  }, 600);

  // Record progress
  fetch("/api/record-progress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word: currentTest.word, correct })
  });

  roundResults.push({ word: currentTest.word, correct });

  if (correct) {
    showFeedback("⭐ Yes! Great job!", "correct");
    speak("Great job!");
  } else {
    showFeedback(`That's "${clicked}". The word was "${currentTest.word}".`, "wrong");
    speak(`Not quite. The word was ${currentTest.word}.`);
  }

  // Disable further clicks, wait then move on
  getTokenEls().forEach(el => {
    el.classList.remove("clickable");
    el.removeEventListener("click", onWordClick);
  });

  setTimeout(nextTest, 2000);
}

// ── Complete screen ────────────────────────────────────────────────────────
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

// ── Screen helper ──────────────────────────────────────────────────────────
function showScreen(target) {
  [startScreen, lessonScreen, completeScreen].forEach(s => {
    s.classList.toggle("hidden", s !== target);
  });
}

// ── Event listeners ────────────────────────────────────────────────────────
btnStart.addEventListener("click", () => loadLesson(null));
btnAgain.addEventListener("click", () => loadLesson(null));

// Ensure voices are loaded (Chrome lazy-loads them)
if (synth.onvoiceschanged !== undefined) {
  synth.onvoiceschanged = () => {};
}
