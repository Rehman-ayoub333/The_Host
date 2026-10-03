import { C } from "./constants.js";
import { audio } from "./audio.js";
import { createRobot } from "./robot.js";
import { presence } from "./presence.js";

const robotMount = document.getElementById("robotMount");
robotMount.innerHTML = `<svg id="robotSvg" viewBox="0 0 200 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="CampusAI robot" style="--eye:#5B6B8C">
  <g id="antenna">
    <line x1="100" y1="34" x2="100" y2="12" stroke="#3B4660" stroke-width="4" stroke-linecap="round"/>
    <circle id="antennaTip" cx="100" cy="8" r="7" fill="var(--eye)"/>
  </g>
  <rect x="18" y="92" width="14" height="44" rx="5" fill="#222B3D" stroke="#3B4660" stroke-width="2"/>
  <rect x="168" y="92" width="14" height="44" rx="5" fill="#222B3D" stroke="#3B4660" stroke-width="2"/>
  <rect x="30" y="34" width="140" height="150" rx="26" fill="#161D2B" stroke="#3B4660" stroke-width="3"/>
  <rect x="48" y="60" width="104" height="50" rx="14" fill="#0A0F18"/>
  <g id="eyes">
    <g id="eyeLeft"><g class="eye-inner">
      <circle class="eye-glow" cx="78" cy="85" r="16" fill="var(--eye)" opacity="0.22"/>
      <circle class="eye-core" cx="78" cy="85" r="10" fill="var(--eye)"/>
    </g></g>
    <g id="eyeRight"><g class="eye-inner">
      <circle class="eye-glow" cx="122" cy="85" r="16" fill="var(--eye)" opacity="0.22"/>
      <circle class="eye-core" cx="122" cy="85" r="10" fill="var(--eye)"/>
    </g></g>
  </g>
  <rect x="52" y="122" width="96" height="50" rx="10" fill="#0A0F18"/>
  <g id="mouth">
    <rect class="bar" x="59"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="77"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="95"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="113" y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="131" y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
  </g>
  <rect x="82" y="184" width="36" height="14" rx="4" fill="#2A3346"/>
  <rect x="50" y="198" width="100" height="42" rx="16" fill="#161D2B" stroke="#3B4660" stroke-width="3"/>
  <circle id="chestLed" cx="100" cy="219" r="6" fill="var(--eye)"/>
</svg>`;

const robot = createRobot(robotMount);
const els = {
  autoGreet: document.getElementById("autoGreet"),
  talkBtn: document.getElementById("talkBtn"),
  doneBtn: document.getElementById("doneBtn"),
  snapBtn: document.getElementById("snapBtn"),
  reconnectBtn: document.getElementById("reconnectBtn"),
  textForm: document.getElementById("textForm"),
  textInput: document.getElementById("textInput"),
  textSend: document.getElementById("textSend"),
  preview: document.getElementById("preview"),
  statusLabel: document.getElementById("statusLabel"),
  hints: document.getElementById("hints"),
  transcript: document.getElementById("transcript"),
  activityLog: document.getElementById("activityLog"),
  recordsBody: document.querySelector("#recordsTable tbody"),
  startOverlay: document.getElementById("startOverlay"),
  startBtn: document.getElementById("startBtn"),
  startNote: document.getElementById("startNote"),
  toast: document.getElementById("toast"),
};

const STATE_LABELS = {
  booth_off: "Ready",
  idle: "Ready",
  noticed: "Oh — hello!",
  connecting: "Connecting…",
  listening: "Listening…",
  thinking: "Thinking…",
  waiting_confirmation: "Waiting for your answer…",
  speaking: "Speaking…",
  error: "Something went wrong. Please try again.",
};
const ACTIVE_STATES = new Set([
  "noticed",
  "connecting",
  "listening",
  "thinking",
  "waiting_confirmation",
  "speaking",
]);
const RECORD_NAMES = {
  query_timetable: "Timetable search",
  check_room_availability: "Room check",
  create_complaint: "Complaint",
  get_complaint_status: "Complaint status",
  list_recent_complaints: "Recent complaints",
  web_search: "Web lookup",
};

let ws = null;
let state = "booth_off";
let endingByUs = false;
let lastActivity = 0;
let sessionStartedAt = 0;
let timers = { tick: null, recover: null, toast: null, snapshot: null };
let armed = true;
let lastAutoGreetAt = 0;
let micAvailable = false;
let cameraAvailable = false;
let presenceAvailable = false;
let autoGreetEnabled = els.autoGreet.checked;
let cameraStream = null;
let lastLine = null;

function now() {
  return Date.now();
}

function isSessionActive() {
  return ACTIVE_STATES.has(state);
}

function setState(nextState, errorMessage = "") {
  state = nextState;
  document.body.dataset.state = nextState;
  robot.setState(nextState);
  els.statusLabel.textContent = nextState === "error"
    ? (errorMessage || STATE_LABELS.error)
    : (STATE_LABELS[nextState] || "Ready");

  els.talkBtn.hidden = nextState !== "idle";
  els.doneBtn.hidden = !ACTIVE_STATES.has(nextState);
  els.snapBtn.disabled = !cameraAvailable || ![
    "listening", "thinking", "waiting_confirmation", "speaking",
  ].includes(nextState);
  els.snapBtn.title = cameraAvailable ? "" : "Camera not available";
  const textEnabled = [
    "listening", "thinking", "waiting_confirmation", "speaking",
  ].includes(nextState);
  els.textInput.disabled = !textEnabled;
  els.textSend.disabled = !textEnabled;
  els.reconnectBtn.hidden = nextState !== "error";
  els.hints.hidden = nextState !== "idle";
}

function showToast(text, ms = 5000) {
  clearTimeout(timers.toast);
  els.toast.textContent = text;
  els.toast.hidden = false;
  timers.toast = setTimeout(() => {
    els.toast.hidden = true;
  }, ms);
}

function makeTranscriptLine(role, text) {
  const line = document.createElement("div");
  line.className = `line line-${role}`;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role === "user" ? "You:" : "CampusAI:";
  const textNode = document.createElement("span");
  textNode.className = "txt";
  textNode.textContent = text;
  line.append(who, document.createTextNode(" "), textNode);
  els.transcript.append(line);
  els.transcript.scrollTop = els.transcript.scrollHeight;
  return textNode;
}

function appendTranscript(role, text) {
  if (lastLine && lastLine.role === role) {
    lastLine.txtEl.textContent += text;
  } else {
    lastLine = {
      role,
      txtEl: makeTranscriptLine(role, text.trimStart()),
    };
  }
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function addTranscriptLine(role, text) {
  makeTranscriptLine(role, text);
  lastLine = null;
}

function sourceLabel(source) {
  if (source === "real") return "Real";
  if (source === "demo") return "Demo";
  if (source === "web") return "Web";
  return "Demo";
}

function sourceClass(source) {
  return `tag-${source === "real" || source === "demo" || source === "web" ? source : "demo"}`;
}

function makeSourceTag(source) {
  const tag = document.createElement("span");
  tag.className = `tag ${sourceClass(source)}`;
  tag.textContent = sourceLabel(source);
  return tag;
}

function upsertActivity(message) {
  let item;
  if (message.status === "running") {
    item = document.createElement("li");
    item.className = "running";
    item.dataset.tool = message.tool;
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const summary = document.createElement("span");
    summary.className = "summary";
    summary.textContent = message.summary || "Working…";
    item.append(time, summary, makeSourceTag(message.source));
    els.activityLog.prepend(item);
  } else {
    item = Array.from(els.activityLog.children).find(
      (entry) => entry.classList.contains("running") && entry.dataset.tool === message.tool,
    );
    if (item) {
      const summary = item.querySelector(".summary");
      summary.textContent = message.summary || "Done";
      item.querySelector(".tag")?.replaceWith(makeSourceTag(message.source));
      item.classList.remove("running");
      item.classList.add("done");
    } else {
      item = document.createElement("li");
      item.className = "done";
      item.dataset.tool = message.tool;
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = new Date().toLocaleTimeString("en-GB", { hour12: false });
      const summary = document.createElement("span");
      summary.className = "summary";
      summary.textContent = message.summary || "Done";
      item.append(time, summary, makeSourceTag(message.source));
      els.activityLog.prepend(item);
    }
  }
  while (els.activityLog.children.length > C.ACTIVITY_LOG_MAX_LINES) {
    els.activityLog.lastElementChild.remove();
  }
}

async function refreshRecords() {
  try {
    const response = await fetch(`/api/records?limit=${C.RECORDS_LIMIT}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const rows = payload.records;
    if (!Array.isArray(rows)) throw new Error("Invalid records response");
    const fragment = document.createDocumentFragment();
    for (const record of rows) {
      const row = document.createElement("tr");
      const time = document.createElement("td");
      time.textContent = record.timestamp.slice(11, 19);
      const action = document.createElement("td");
      action.textContent = RECORD_NAMES[record.tool] || record.tool;
      const result = document.createElement("td");
      result.textContent = record.summary;
      const source = document.createElement("td");
      source.append(makeSourceTag(record.source));
      row.append(time, action, result, source);
      fragment.append(row);
    }
    els.recordsBody.replaceChildren(fragment);
  } catch (error) {
    console.error("Failed to refresh recent actions:", error);
  }
}

function handleControl(message) {
  if (message.type === "state") {
    if (!isSessionActive()) return;
    setState(message.value);
  } else if (message.type === "transcript") {
    lastActivity = now();
    appendTranscript(message.role, message.text);
  } else if (message.type === "tool_event") {
    lastActivity = now();
    upsertActivity(message);
    if (message.status === "done") refreshRecords();
  } else if (message.type === "interrupted") {
    audio.flushPlayback();
  } else if (message.type === "error") {
    fail(message.message);
  }
}

function onMicFrame(buffer) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(buffer);
}

async function startSession(trigger) {
  if (isSessionActive()) return;
  els.transcript.replaceChildren();
  lastLine = null;
  clearTimeout(timers.recover);
  timers.recover = null;
  setState(trigger === "presence" ? "noticed" : "connecting");

  if (micAvailable) {
    try {
      await audio.startMic(onMicFrame);
    } catch {
      micAvailable = false;
      showToast("Microphone unavailable — you can type instead.", 6000);
    }
  }

  endingByUs = false;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  try {
    ws = new WebSocket(`${protocol}://${location.host}/ws/session?trigger=${trigger}`);
  } catch {
    fail("Connection lost.");
    return;
  }
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    sessionStartedAt = lastActivity = now();
    clearInterval(timers.tick);
    timers.tick = setInterval(tickCheck, 1000);
  };
  ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      lastActivity = now();
      audio.playPcm(event.data);
      return;
    }
    try {
      handleControl(JSON.parse(event.data));
    } catch {
      console.error("Invalid control message from backend.");
    }
  };
  ws.onerror = () => {
    if (!endingByUs) fail("Connection lost.");
  };
  ws.onclose = () => {
    if (!endingByUs) fail("Connection lost.");
  };
}

function endSession(reason) {
  endingByUs = true;
  clearInterval(timers.tick);
  timers.tick = null;
  audio.stopMic();
  audio.flushPlayback();
  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  ws = null;
  armed = presence.state === "absent";
  if (reason === "cap") showToast("Conversation ended — tap to talk again.", 5000);
  if (reason !== "error") setState("idle");
}

function tickCheck() {
  const current = now();
  if (current - lastActivity >= C.AUTO_RESET_MS) {
    endSession("timeout");
  } else if (current - sessionStartedAt >= C.MAX_SESSION_MS) {
    endSession("cap");
  }
}

function fail(message) {
  if (state === "error") {
    els.statusLabel.textContent = message || STATE_LABELS.error;
  } else {
    setState("error", message || STATE_LABELS.error);
  }
  if (!endingByUs) endSession("error");
  clearTimeout(timers.recover);
  timers.recover = setTimeout(() => {
    if (state === "error") setState("idle");
  }, C.ERROR_AUTO_RECOVER_MS);
}

function onArrival() {
  robot.perkAntenna();
  if (
    autoGreetEnabled
    && state === "idle"
    && armed
    && now() - lastAutoGreetAt >= C.GREET_COOLDOWN_MS
    && document.visibilityState === "visible"
  ) {
    lastAutoGreetAt = now();
    armed = false;
    startSession("presence");
  }
}

function onAbsent() {
  armed = true;
}

function onFace(face) {
  robot.setEyeTarget(face);
}

async function startBooth() {
  els.startBtn.disabled = true;
  els.startBtn.textContent = "Starting…";
  try {
    await audio.init();
  } catch {
    els.startBtn.disabled = false;
    els.startBtn.textContent = "Start Booth";
    els.startNote.textContent = "Audio could not be initialized.";
    return;
  }
  micAvailable = await audio.probeMic();
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: "user",
      },
    });
    els.preview.srcObject = cameraStream;
    await els.preview.play();
    cameraAvailable = true;
  } catch {
    cameraAvailable = false;
  }
  if (cameraAvailable) {
    try {
      await presence.init(els.preview, { onArrival, onAbsent, onFace });
      presenceAvailable = true;
    } catch (error) {
      console.error(error);
      presenceAvailable = false;
    }
  }
  const notes = [];
  if (!micAvailable) notes.push("Microphone blocked — voice is off; you can type instead.");
  if (!cameraAvailable) notes.push("Camera blocked — greeting and photos are off.");
  else if (!presenceAvailable) notes.push("Presence detection unavailable — use Tap to Talk.");
  els.startNote.textContent = notes.join(" ");
  els.startOverlay.hidden = true;
  els.startOverlay.style.display = "none";
  setState("idle");
  refreshRecords();
  if (notes.length) showToast(notes.join(" "), 8000);
}

function captureSnapshot() {
  if (!cameraAvailable || !ws || ws.readyState !== WebSocket.OPEN) return;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = C.SNAPSHOT_WIDTH;
    canvas.height = C.SNAPSHOT_HEIGHT;
    const context = canvas.getContext("2d");
    context.drawImage(els.preview, 0, 0, C.SNAPSHOT_WIDTH, C.SNAPSHOT_HEIGHT);
    const dataUrl = canvas.toDataURL("image/jpeg", C.SNAPSHOT_QUALITY);
    const imageBase64 = dataUrl.slice("data:image/jpeg;base64,".length);
    ws.send(JSON.stringify({ type: "vision_frame", image_base64: imageBase64 }));
    lastActivity = now();
    els.snapBtn.textContent = "Sent ✓";
    clearTimeout(timers.snapshot);
    timers.snapshot = setTimeout(() => {
      els.snapBtn.textContent = "Show It Something";
    }, 1200);
  } catch {
    showToast("The camera frame could not be sent.");
  }
}

els.startBtn.addEventListener("click", startBooth);
els.talkBtn.addEventListener("click", () => startSession("button"));
els.doneBtn.addEventListener("click", () => endSession("user"));
els.snapBtn.addEventListener("click", captureSnapshot);
els.reconnectBtn.addEventListener("click", () => {
  clearTimeout(timers.recover);
  timers.recover = null;
  startSession("button");
});
els.autoGreet.addEventListener("change", () => {
  autoGreetEnabled = els.autoGreet.checked;
});
els.textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.textInput.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  addTranscriptLine("user", text);
  ws.send(JSON.stringify({ type: "text_input", text }));
  els.textInput.value = "";
  lastActivity = now();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && isSessionActive()) endSession("user");
});
window.addEventListener("beforeunload", () => {
  endingByUs = true;
  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  audio.stopMic();
  if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
});

setState("booth_off");