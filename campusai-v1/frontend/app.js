import { C } from "./constants.js";
import { audio } from "./audio.js";
import { createRobot } from "./robot.js";
import { presence } from "./presence.js";

const robotMount = document.getElementById("robotMount");
const robot = createRobot(robotMount);
robot.setAmplitudeSources({
  getMicAmp: () => audio.getMicAmp(),
  getPlaybackAmp: () => audio.getPlaybackAmp(),
});
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
  taking_order: "Taking the order…",
  needs_help: "Calling a team member…",
  speaking: "Speaking…",
  error: "Something went wrong. Please try again.",
};
const ACTIVE_STATES = new Set([
  "noticed",
  "connecting",
  "listening",
  "thinking",
  "taking_order",
  "needs_help",
  "speaking",
]);
const BACKEND_STATE_MAP = {
  LISTENING: "listening",
  THINKING: "thinking",
  SEEING: "thinking",
  REMEMBERING: "thinking",
  SPEAKING: "speaking",
  GREETING: "speaking",
  RECOMMENDING: "speaking",
  ANNOUNCING: "speaking",
  TAKING_ORDER: "taking_order",
  NEEDS_HELP: "needs_help",
};
const ROBOT_VISUAL = { taking_order: "waiting_confirmation", needs_help: "thinking" };

let ws = null;
let state = "booth_off";
let endingByUs = false;
let lastActivity = 0;
let sessionStartedAt = 0;
let timers = { tick: null, recover: null, toast: null, snapshot: null, voiceActivity: null };
let armed = true;
let lastAutoGreetAt = 0;
let micAvailable = false;
let cameraAvailable = false;
let presenceAvailable = false;
let autoGreetEnabled = els.autoGreet.checked;
let cameraStream = null;
let lastLine = null;
const vision = { sentPresent: null, sentPeople: null, sentAt: 0, warned: false, timer: null };
const voice = { onPolls: 0, belowSince: 0, sent: false };

function now() {
  return Date.now();
}

function isSessionActive() {
  return ACTIVE_STATES.has(state);
}

function setState(nextState, errorMessage = "") {
  state = nextState;
  document.body.dataset.state = nextState;
  robot.setState(ROBOT_VISUAL[nextState] || nextState);
  els.statusLabel.textContent = nextState === "error"
    ? (errorMessage || STATE_LABELS.error)
    : (STATE_LABELS[nextState] || "Ready");

  els.talkBtn.hidden = nextState !== "idle";
  els.doneBtn.hidden = !ACTIVE_STATES.has(nextState);
  els.snapBtn.disabled = !cameraAvailable || ![
    "listening", "thinking", "taking_order", "needs_help", "speaking",
  ].includes(nextState);
  els.snapBtn.title = cameraAvailable ? "" : "Camera not available";
  const textEnabled = [
    "listening", "thinking", "taking_order", "needs_help", "speaking",
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
  line.className = `line line-${role === "visitor" ? "user" : "agent"}`;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role === "visitor" ? "You:" : `${C.AGENT_LABEL}:`;
  const textNode = document.createElement("span");
  textNode.className = "txt";
  textNode.textContent = text;
  line.append(who, document.createTextNode(" "), textNode);
  els.transcript.append(line);
  els.transcript.scrollTop = els.transcript.scrollHeight;
  return textNode;
}

function appendTranscript(role, text, final) {
  if (lastLine && lastLine.role === role && lastLine.final === false) {
    lastLine.txtEl.textContent = text;
  } else {
    lastLine = { role, txtEl: makeTranscriptLine(role, text), final };
  }
  lastLine.final = final;
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function reportVision(force) {
  const payload = {
    present: presence.state === "present",
    people: Math.min(presence.people, 50),
    objects: [],
  };
  const changed = payload.people !== vision.sentPeople;
  const due = Date.now() - vision.sentAt >= C.VISION_REPORT_MS;
  if (!force && !(changed && due)) return;

  vision.sentPresent = payload.present;
  vision.sentPeople = payload.people;
  vision.sentAt = Date.now();
  fetch("/api/vision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((response) => {
      if (!response.ok && !vision.warned) {
        vision.warned = true;
        console.warn(`Presence reporting failed: HTTP ${response.status}`);
      }
    })
    .catch(() => {
      if (!vision.warned) {
        vision.warned = true;
        console.warn("Presence reporting is unavailable.");
      }
    });
}

function sendVoiceActivity(active) {
  // Never the same value twice in a row, and never a level: the backend only
  // needs to know whether the guest is talking right now (16 section 2f item 2).
  if (voice.sent === active) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  voice.sent = active;
  ws.send(JSON.stringify({ type: "voice_activity", active }));
}

function pollVoiceActivity() {
  if (!isSessionActive() || !ws || ws.readyState !== WebSocket.OPEN) return;
  if (audio.getMicAmp() >= C.VOICE_ACTIVE_LEVEL) {
    voice.belowSince = 0;
    voice.onPolls += 1;
    // 0.05 of playback means THE HOST is speaking, so this is its own voice
    // coming back through the microphone, not the guest.
    if (voice.onPolls >= C.VOICE_ON_POLLS && audio.getPlaybackAmp() < 0.05) {
      sendVoiceActivity(true);
    }
    return;
  }
  voice.onPolls = 0;
  if (!voice.belowSince) voice.belowSince = now();
  if (now() - voice.belowSince >= C.VOICE_OFF_MS) sendVoiceActivity(false);
}

function startVoiceActivity() {
  // The backend hears the guest only when Gemini transcribes them, a second or
  // more after the first syllable, which is too late to hold an announcement
  // back. The mic meter the robot face already uses knows sooner.
  stopVoiceActivity();
  voice.onPolls = 0;
  voice.belowSince = 0;
  voice.sent = false;
  timers.voiceActivity = setInterval(pollVoiceActivity, C.VOICE_POLL_MS);
}

function stopVoiceActivity() {
  clearInterval(timers.voiceActivity);
  timers.voiceActivity = null;
}

function handleControl(message) {
  if (message.type === "agent_state_changed") {
    if (!isSessionActive()) return;
    const local = BACKEND_STATE_MAP[message.state];
    if (local) setState(local);
  } else if (message.type === "speech_transcript") {
    lastActivity = now();
    appendTranscript(message.role, message.text, Boolean(message.final));
  } else if (message.type === "capture_request") {
    if (isSessionActive()) captureSnapshot();
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
    startVoiceActivity();
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
  stopVoiceActivity();
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
  reportVision(true);
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
  reportVision(true);
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
      reportVision(true);
      vision.timer = setInterval(() => reportVision(false), C.VISION_REPORT_MS);
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
  ws.send(JSON.stringify({ type: "text_input", text }));
  els.textInput.value = "";
  lastActivity = now();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && isSessionActive()) endSession("user");
});
window.addEventListener("beforeunload", () => {
  clearInterval(vision.timer);
  stopVoiceActivity();
  endingByUs = true;
  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  audio.stopMic();
  if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
});

setState("booth_off");