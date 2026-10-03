import { C } from "./constants.js";

let detector = null;
let videoEl = null;
let intervalId = null;
let currentState = "absent";
let consecutive = 0;
let lastFaceAt = 0;
let errorLogged = false;
let callbacks = {
  onArrival() {},
  onAbsent() {},
  onFace() {},
};

function tick() {
  if (
    !detector
    || document.hidden
    || videoEl.readyState < 2
    || videoEl.videoWidth === 0
  ) return;

  try {
    const now = performance.now();
    const result = detector.detectForVideo(videoEl, now);
    let largest = null;

    for (const detection of result.detections) {
      const box = detection.boundingBox;
      if (!box || box.width / videoEl.videoWidth < C.MIN_FACE_WIDTH_RATIO) continue;
      if (!largest || box.width > largest.width) largest = box;
    }

    const face = largest
      ? {
          x: (largest.originX + largest.width / 2) / videoEl.videoWidth,
          y: (largest.originY + largest.height / 2) / videoEl.videoHeight,
        }
      : null;
    callbacks.onFace(face);

    if (face) {
      consecutive += 1;
      lastFaceAt = now;
      if (currentState === "absent" && consecutive >= C.ARRIVAL_CONSECUTIVE) {
        currentState = "present";
        callbacks.onArrival();
      }
    } else {
      consecutive = 0;
      if (currentState === "present" && now - lastFaceAt >= C.ABSENCE_MS) {
        currentState = "absent";
        callbacks.onAbsent();
      }
    }
  } catch (error) {
    if (!errorLogged) {
      errorLogged = true;
      console.error("Face presence detection failed:", error);
    }
  }
}

export const presence = {
  get state() {
    return currentState;
  },

  async init(video, handlers = {}) {
    this.stop();
    currentState = "absent";
    consecutive = 0;
    lastFaceAt = 0;
    errorLogged = false;
    videoEl = video;
    callbacks = {
      onArrival: handlers.onArrival || (() => {}),
      onAbsent: handlers.onAbsent || (() => {}),
      onFace: handlers.onFace || (() => {}),
    };

    const { FaceDetector, FilesetResolver } = await import(
      "./vendor/mediapipe/vision_bundle.mjs"
    );
    const fileset = await FilesetResolver.forVisionTasks("/vendor/mediapipe/wasm");
    detector = await FaceDetector.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: "/vendor/mediapipe/blaze_face_short_range.tflite",
        delegate: "CPU",
      },
      runningMode: "VIDEO",
      minDetectionConfidence: C.MIN_DETECTION_CONFIDENCE,
    });
    intervalId = setInterval(tick, C.DETECT_INTERVAL_MS);
  },

  stop() {
    if (intervalId !== null) clearInterval(intervalId);
    intervalId = null;
    if (detector) {
      try {
        detector.close();
      } catch (error) {
        if (!errorLogged) console.error("Could not close face detector:", error);
      }
    }
    detector = null;
    videoEl = null;
    consecutive = 0;
    lastFaceAt = 0;
    if (currentState === "present") {
      currentState = "absent";
      callbacks.onAbsent();
    }
  },
};