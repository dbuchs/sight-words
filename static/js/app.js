/**
 * Sight Words Learning App
 * Lesson flow:
 *   Phase 0 - Demo: app reads sentence 1 aloud with highlighting
 *   Phase 1 - Practice: student reads sentence 2
 *   Phase 2-3 - Click-to-identify words from sentence 2
 *   Complete screen
 */

"use strict";

// State
let lesson = null;
let phase = 0;
let testQueue = [];
let currentTest = null;
let roundResults = [];
let currentStudentId = null;
let lastSightWord = "";
let sessionWords = new Set();
let pinBuffer = "";
let pendingPinAction = "lesson";
let schedulePanelLoadedForStudent = null;

// DOM refs
const startScreen = document.getElementById("start-screen");
const pinScreen = document.getElementById("pin-screen");
const lessonScreen = document.getElementById("lesson-screen");
const completeScreen = document.getElementById("complete-screen");
const sightWordDisplay = document.getElementById("sight-word-display");
const sentenceEl = document.getElementById("sentence-text");
const instructionEl = document.getElementById("instruction-area");
const feedbackEl = document.getElementById("feedback");
const btnReplay = document.getElementById("btn-replay");
const btnNext = document.getElementById("btn-next");
const phaseLabel = document.getElementById("phase-label");
const roundSummary = document.getElementById("round-summary");
const btnStart = document.getElementById("btn-start");
const btnAgain = document.getElementById("btn-again");
const dots = [0, 1, 2, 3].map(i => document.getElementById(`dot-${i}`));

// Student UI refs
const studentSelect = document.getElementById("student-select");
const btnAddStudent = document.getElementById("btn-add-student");
const newStudentForm = document.getElementById("new-student-form");
const newStudentName = document.getElementById("new-student-name");
const newStudentPin = document.getElementById("new-student-pin");
const btnSaveStudent = document.getElementById("btn-save-student");
const btnCancelStudent = document.getElementById("btn-cancel-student");
const btnManageWords = document.getElementById("btn-manage-words");
const wordSchedulePanel = document.getElementById("word-schedule-panel");
const btnCloseWordPanel = document.getElementById("btn-close-word-panel");
const wordSelect = document.getElementById("word-select");
const wordScheduleSummary = document.getElementById("word-schedule-summary");
const wordIntervalInput = document.getElementById("word-interval");
const wordNextReviewInput = document.getElementById("word-next-review");
const btnSaveWordSchedule = document.getElementById("btn-save-word-schedule");
const wordScheduleMsg = document.getElementById("word-schedule-msg");

// PIN screen refs
const pinStudentName = document.getElementById("pin-student-name");
const pinDots = document.querySelectorAll(".pin-dot");
const pinError = document.getElementById("pin-error");
const pinOkBtn = document.getElementById("pin-ok");
const pinClearBtn = document.getElementById("pin-clear");
const btnPinBack = document.getElementById("btn-pin-back");

// Audio refs
const ttsAudio = document.getElementById("tts-audio");
const audioPendingEl = document.getElementById("audio-pending");
let ttsObjectUrl = null;
const ttsCache = new Map();
const clickAudio = new Audio();
let clickObjectUrl = null;

function getStudentId() {
  const value = studentSelect && studentSelect.value;
  return value ? parseInt(value, 10) : 1;
}

function getSelectedStudent() {
  return studentSelect && studentSelect.options[studentSelect.selectedIndex];
}

function updatePinDots() {
  pinDots.forEach((dot, index) => {
    dot.classList.toggle("filled", index < pinBuffer.length);
  });
}

function showScreen(target) {
  [startScreen, pinScreen, lessonScreen, completeScreen].forEach(screen => {
    screen.classList.toggle("hidden", screen !== target);
  });
}

function setWordScheduleMessage(message, type) {
  if (!wordScheduleMsg) return;
  wordScheduleMsg.textContent = message;
  wordScheduleMsg.style.color = type === "error" ? "var(--danger)" : "var(--success)";
  wordScheduleMsg.classList.remove("hidden");
}

function clearWordScheduleMessage() {
  if (!wordScheduleMsg) return;
  wordScheduleMsg.textContent = "";
  wordScheduleMsg.classList.add("hidden");
}

function formatStoredDateForInput(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function populateWordOptions() {
  if (!wordSelect) return;
  const words = Array.isArray(window.sightWords) ? window.sightWords : [];
  wordSelect.innerHTML = words
    .map(word => `<option value="${word}">${word}</option>`)
    .join("");
}

async function loadSelectedWordSchedule() {
  if (!wordSelect || !wordSelect.value) return;

  clearWordScheduleMessage();
  wordScheduleSummary.textContent = "Loading word details...";

  const res = await fetch(`/api/progress/${encodeURIComponent(wordSelect.value)}?student_id=${getStudentId()}`);
  const data = await res.json();

  const attempts = data.attempts || 0;
  const correct = data.correct || 0;
  const status = data.status || "unseen";
  const interval = Number.isInteger(data.interval) ? data.interval : 1;

  wordIntervalInput.value = interval;
  wordNextReviewInput.value = formatStoredDateForInput(data.next_review);
  wordScheduleSummary.textContent =
    `Status: ${status} | Correct: ${correct}/${attempts} | Current interval: ${interval} day${interval === 1 ? "" : "s"}`;
}

async function ensureWordSchedulePanelLoaded(forceReload = false) {
  if (!wordSchedulePanel) return;

  const studentId = getStudentId();
  if (!wordSelect.options.length) {
    populateWordOptions();
  }

  if (!forceReload && schedulePanelLoadedForStudent === studentId) {
    return;
  }

  schedulePanelLoadedForStudent = studentId;
  await loadSelectedWordSchedule();
}

async function openWordSchedulePanel() {
  if (!wordSchedulePanel) return;
  pendingPinAction = "manage_words";
  wordSchedulePanel.classList.remove("hidden");
  showScreen(startScreen);
  await ensureWordSchedulePanelLoaded(true);
}

function showPinScreenFor(action) {
  const selected = getSelectedStudent();
  pendingPinAction = action;
  pinBuffer = "";
  updatePinDots();
  pinError.classList.add("hidden");
  pinStudentName.textContent = `${selected ? selected.textContent : "Student"} - Enter PIN`;
  showScreen(pinScreen);
}

// Student and schedule controls
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
      const option = document.createElement("option");
      option.value = student.id;
      option.textContent = student.name;
      option.dataset.hasPin = student.has_pin ? "true" : "false";
      studentSelect.appendChild(option);
      studentSelect.value = student.id;
      newStudentForm.classList.add("hidden");
      newStudentName.value = "";
      if (newStudentPin) newStudentPin.value = "";
      schedulePanelLoadedForStudent = null;
    } else {
      const error = await res.json();
      alert(error.error || "Could not save student.");
    }
  });
}

if (studentSelect) {
  studentSelect.addEventListener("change", async () => {
    schedulePanelLoadedForStudent = null;
    if (wordSchedulePanel && !wordSchedulePanel.classList.contains("hidden")) {
      await ensureWordSchedulePanelLoaded(true);
    }
  });
}

if (btnManageWords) {
  btnManageWords.addEventListener("click", async () => {
    const selected = getSelectedStudent();
    const hasPin = selected && selected.dataset.hasPin === "true";
    if (hasPin) {
      showPinScreenFor("manage_words");
      return;
    }
    await openWordSchedulePanel();
  });
}

if (btnCloseWordPanel) {
  btnCloseWordPanel.addEventListener("click", () => {
    wordSchedulePanel.classList.add("hidden");
    clearWordScheduleMessage();
  });
}

if (wordSelect) {
  wordSelect.addEventListener("change", () => {
    loadSelectedWordSchedule();
  });
}

if (btnSaveWordSchedule) {
  btnSaveWordSchedule.addEventListener("click", async () => {
    const word = wordSelect && wordSelect.value;
    const interval = wordIntervalInput && wordIntervalInput.value.trim();
    const nextReview = wordNextReviewInput && wordNextReviewInput.value;

    if (!word) {
      setWordScheduleMessage("Choose a word first.", "error");
      return;
    }
    if (interval === "" || !/^\d+$/.test(interval)) {
      setWordScheduleMessage("Interval must be a whole number.", "error");
      return;
    }
    if (!nextReview) {
      setWordScheduleMessage("Choose a next due date.", "error");
      return;
    }

    const res = await fetch(`/api/progress/${encodeURIComponent(word)}/schedule`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: getStudentId(),
        interval: parseInt(interval, 10),
        next_review: nextReview,
      }),
    });
    const data = await res.json();

    if (!res.ok) {
      setWordScheduleMessage(data.error || "Could not update schedule.", "error");
      return;
    }

    setWordScheduleMessage("Schedule updated.", "success");
    await loadSelectedWordSchedule();
  });
}

// PIN controls
document.querySelectorAll(".pin-key[data-digit]").forEach(button => {
  button.addEventListener("click", () => {
    if (pinBuffer.length < 8) {
      pinBuffer += button.dataset.digit;
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
      if (pendingPinAction === "manage_words") {
        await openWordSchedulePanel();
      } else {
        loadLesson(null);
      }
    } else {
      pinError.classList.remove("hidden");
      pinBuffer = "";
      updatePinDots();
    }
  });
}

// OpenAI TTS helpers
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
  } catch (error) {
    console.warn("TTS error:", error);
    resetAudioPending();
    if (onEnd) onEnd();
  }
}

async function speakWordTest(word, { onEnd = null } = {}) {
  function waitForAudioEnd() {
    return new Promise(resolve => {
      ttsAudio.onended = resolve;
    });
  }

  try {
    const [promptBlob, wordBlob] = await Promise.all([
      fetchTtsBlobCached("Click the word"),
      fetchTtsBlobCached(word, "word"),
    ]);

    showAudioPending();

    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(promptBlob);
    ttsAudio.src = ttsObjectUrl;
    showAudioPlaying();
    await ttsAudio.play();
    await waitForAudioEnd();

    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(wordBlob);
    ttsAudio.src = ttsObjectUrl;
    await ttsAudio.play();
    await waitForAudioEnd();

    hideAudioPending();
    if (onEnd) onEnd();
  } catch (error) {
    console.warn("TTS word-test error:", error);
    resetAudioPending();
    if (onEnd) onEnd();
  }
}

function prewarmTtsCache() {
  [
    "Click the word",
    "Great job!",
    "Amazing! You got them all right!",
    "Good work! Keep practising!",
    "Now you read this sentence out loud!",
  ].forEach(phrase => fetchTtsBlobCached(phrase).catch(() => {}));
}

async function speakWordClick(word) {
  try {
    const blob = await fetchTtsBlobCached(word, "word");
    if (clickObjectUrl) URL.revokeObjectURL(clickObjectUrl);
    clickObjectUrl = URL.createObjectURL(blob);
    clickAudio.src = clickObjectUrl;
    clickAudio.play().catch(() => {});
  } catch (_error) {
    // Ignore click-preview errors silently.
  }
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
      let index = 0;
      const intervalId = setInterval(() => {
        tokenEls.forEach(el => el.classList.remove("speaking"));
        if (index < tokenEls.length) tokenEls[index].classList.add("speaking");
        index += 1;
        if (index >= tokenEls.length) clearInterval(intervalId);
      }, msPerWord);
    };

    ttsAudio.onended = () => {
      tokenEls.forEach(el => el.classList.remove("speaking"));
      hideAudioPending();
      if (onEnd) onEnd();
    };

    await ttsAudio.play();
  } catch (error) {
    console.warn("TTS error:", error);
    resetAudioPending();
    const words = sentence.split(/\s+/);
    const msPerWord = 600;
    let index = 0;
    const intervalId = setInterval(() => {
      tokenEls.forEach(el => el.classList.remove("speaking"));
      if (index < tokenEls.length) tokenEls[index].classList.add("speaking");
      index += 1;
      if (index >= tokenEls.length) {
        clearInterval(intervalId);
        tokenEls.forEach(el => el.classList.remove("speaking"));
        if (onEnd) onEnd();
      }
    }, msPerWord);
  }
}

function buildTokens(sentence, sightWord, clickable = false, highlightSightWord = true, hoverable = false) {
  sentenceEl.innerHTML = "";
  const rawWords = sentence.split(/\s+/);
  const tokens = [];

  rawWords.forEach((raw, index) => {
    const span = document.createElement("span");
    span.classList.add("word-token");
    span.dataset.word = raw.replace(/[^a-zA-Z'-]/g, "").toLowerCase();
    span.textContent = index < rawWords.length - 1 ? `${raw} ` : raw;

    if (highlightSightWord && span.dataset.word === sightWord.toLowerCase()) {
      span.classList.add("sight-word");
    }
    if (clickable) {
      span.classList.add("clickable");
      span.addEventListener("click", onWordClick);
    }
    if (hoverable) {
      span.classList.add("hoverable");
      span.title = "Click to hear this word";
      span.addEventListener("click", () => speakWordClick(span.dataset.word));
    }

    sentenceEl.appendChild(span);
    tokens.push(span);
  });

  return tokens;
}

function getTokenEls() {
  return Array.from(sentenceEl.querySelectorAll(".word-token"));
}

function setPhase(nextPhase) {
  phase = nextPhase;
  dots.forEach((dot, index) => {
    dot.classList.remove("active", "done");
    if (index < nextPhase) dot.classList.add("done");
    if (index === nextPhase) dot.classList.add("active");
  });
}

function setInstruction(html) {
  instructionEl.innerHTML = html;
}

function showFeedback(message, type) {
  feedbackEl.textContent = message;
  feedbackEl.className = `feedback ${type}`;
  feedbackEl.classList.remove("hidden");
  setTimeout(() => feedbackEl.classList.add("hidden"), 1800);
}

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
  testQueue = [
    { word: lesson.sight_word, isSightWord: true },
    ...lesson.test_words.map(word => ({ word, isSightWord: false })),
  ];

  runPhase0();
}

function runPhase0() {
  setPhase(0);
  phaseLabel.textContent = "Listen";
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");

  const tokens = buildTokens(lesson.demo_sentence, lesson.sight_word, false, true, true);
  setInstruction("Listen carefully! The <u>underlined word</u> is our new sight word.");

  speakSentenceWithHighlight(lesson.demo_sentence, tokens, () => {
    btnReplay.classList.remove("hidden");
    btnNext.classList.remove("hidden");
    btnNext.textContent = "I'm ready to read";
    btnNext.onclick = runPhase1;
    btnReplay.onclick = () => speakSentenceWithHighlight(lesson.demo_sentence, getTokenEls(), () => {});
  });
}

function runPhase1() {
  setPhase(1);
  phaseLabel.textContent = "Read";
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");

  buildTokens(lesson.practice_sentence, lesson.sight_word, false, false, true);
  const instructionText = "Now you read this sentence out loud!";
  setInstruction(instructionText);

  speak(instructionText, {
    onEnd: () => {
      btnNext.textContent = "I read it!";
      btnNext.classList.remove("hidden");
      btnNext.onclick = startTestQueue;
    },
  });
}

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
  const dotIndex = Math.min(4 - testQueue.length, 3);
  setPhase(dotIndex);
  phaseLabel.textContent = "Find it";
  btnReplay.classList.add("hidden");
  btnNext.classList.add("hidden");

  buildTokens(lesson.practice_sentence, lesson.sight_word, true, false);
  setInstruction("Listen for the word to find...");

  speakWordTest(currentTest.word, {
    onEnd: () => {
      btnReplay.textContent = "Replay";
      btnReplay.onclick = () => {
        btnReplay.classList.add("hidden");
        speakWordTest(currentTest.word, {
          onEnd: () => btnReplay.classList.remove("hidden"),
        });
      };
      btnReplay.classList.remove("hidden");
    },
  });
}

function onWordClick(event) {
  const clicked = event.currentTarget.dataset.word;
  const target = currentTest.word.replace(/[^a-zA-Z'-]/g, "").toLowerCase();
  const correct = clicked === target;

  event.currentTarget.classList.add(correct ? "correct-flash" : "wrong-flash");
  setTimeout(() => {
    event.currentTarget.classList.remove("correct-flash", "wrong-flash");
  }, 600);

  fetch("/api/record-progress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word: currentTest.word, correct, student_id: currentStudentId }),
  });

  roundResults.push({ word: currentTest.word, correct });

  if (correct) {
    showFeedback("Yes! Great job!", "correct");
    speak("Great job!");
  } else {
    showFeedback(`That's "${clicked}". The word was "${currentTest.word}".`, "wrong");
    speak(`Not quite. The word was ${currentTest.word}.`);
  }

  btnReplay.classList.add("hidden");
  getTokenEls().forEach(el => {
    el.classList.remove("clickable");
    el.removeEventListener("click", onWordClick);
  });

  setTimeout(nextTest, 2000);
}

function runComplete() {
  showScreen(completeScreen);
  const correct = roundResults.filter(result => result.correct).length;
  const total = roundResults.length;
  let html = `<p class="score-line">You got <strong>${correct} out of ${total}</strong> right!</p><br>`;
  roundResults.forEach(result => {
    html += `<span>${result.correct ? "Correct" : "Missed"} <em>${result.word}</em></span><br>`;
  });
  roundSummary.innerHTML = html;
  speak(correct === total ? "Amazing! You got them all right!" : "Good work! Keep practising!");
}

// Primary actions
if (btnStart) {
  btnStart.addEventListener("click", () => {
    const selected = getSelectedStudent();
    const hasPin = selected && selected.dataset.hasPin === "true";
    sessionWords = new Set();
    lastSightWord = "";
    pendingPinAction = "lesson";

    if (hasPin) {
      showPinScreenFor("lesson");
    } else {
      loadLesson(null);
    }
  });
}

if (btnAgain) {
  btnAgain.addEventListener("click", () => loadLesson(null));
}

populateWordOptions();
prewarmTtsCache();
