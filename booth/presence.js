import { C } from "./constants.js";

let detector = null;
let videoEl = null;
let intervalId = null;
let currentState = "absent";
let consecutive = 0;
let lastFaceAt = 0;
let lastPeople = 0;
let errorLogged = false;
let callbacks = {
  onArrival() {},
  onAbsent() {},
  onFace() {},
};

function isFrontal(detection) {
  // 16 section 2h item 2: a face pointed at the screen has its nose close to the
  // midpoint between the eyes; a face turned away does not. Measured against the
  // eye separation so it does not change with distance. Without keypoints there
  // is no evidence the guest is looking at THE HOST, so the face does not count.
  const points = detection.keypoints;
  if (!points || points.length < 3) return false;
  const [rightEye, leftEye, nose] = points;
  if (!rightEye || !leftEye || !nose) return false;
  const span = Math.abs(leftEye.x - rightEye.x);
  if (!span) return false;
  return Math.abs(nose.x - (leftEye.x + rightEye.x) / 2) / span < C.WAKE_FRONTAL_MAX;
}

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
    let largestDetection = null;
    let people = 0;

    for (const detection of result.detections) {
      const box = detection.boundingBox;
      if (!box || box.width / videoEl.videoWidth < C.MIN_FACE_WIDTH_RATIO) continue;
      people += 1;
      if (!largest || box.width > largest.width) {
        largest = box;
        largestDetection = detection;
      }
    }
    lastPeople = people;

    const face = largest
      ? {
          x: (largest.originX + largest.width / 2) / videoEl.videoWidth,
          y: (largest.originY + largest.height / 2) / videoEl.videoHeight,
          // 16 section 2h items 2 and 6: what wake-on-speech tests and what the
          // ?debug=mic readout prints. The robot face ignores both.
          ratio: largest.width / videoEl.videoWidth,
          frontal: isFrontal(largestDetection),
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

  get people() {
    return lastPeople;
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
    lastPeople = 0;
    if (currentState === "present") {
      currentState = "absent";
      callbacks.onAbsent();
    }
  },
};