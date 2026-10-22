/**
 * 16 §2t item 3: the voice page's camera presence and face detection, ported.
 *
 * MediaPipe's vendored files live in `public/vendor/mediapipe/`, so the paths
 * below are the dashboard's own, served from its origin. The rules — arrival
 * after three consecutive detections, absence after 6 s, the frontal test from
 * the keypoints — are unchanged from `booth/presence.js`.
 */
import { C } from "./constants";

export interface FaceReading {
  x: number;
  y: number;
  /** 16 §2h items 2 and 6: what wake-on-speech tests and ?debug=mic prints. */
  ratio: number;
  frontal: boolean;
}

export interface PresenceHandlers {
  onArrival?: () => void;
  onAbsent?: () => void;
  onFace?: (face: FaceReading | null) => void;
}

export interface PresencePort {
  readonly state: "absent" | "present";
  readonly people: number;
  init(video: HTMLVideoElement, handlers?: PresenceHandlers): Promise<void>;
  stop(): void;
}

interface Keypoint {
  x: number;
  y: number;
}

interface Detection {
  boundingBox?: { originX: number; originY: number; width: number; height: number };
  keypoints?: Keypoint[];
}

let detector: { detectForVideo(video: HTMLVideoElement, now: number): { detections: Detection[] }; close(): void } | null = null;
let videoEl: HTMLVideoElement | null = null;
let intervalId: ReturnType<typeof setInterval> | null = null;
let currentState: "absent" | "present" = "absent";
let consecutive = 0;
let lastFaceAt = 0;
let lastPeople = 0;
let errorLogged = false;
let callbacks: Required<PresenceHandlers> = {
  onArrival() {},
  onAbsent() {},
  onFace() {},
};

export function isFrontal(detection: Detection | null): boolean {
  // 16 §2h item 2: a face pointed at the screen has its nose close to the
  // midpoint between the eyes; a face turned away does not. Measured against the
  // eye separation so it does not change with distance. Without keypoints there
  // is no evidence the guest is looking at THE HOST, so the face does not count.
  const points = detection?.keypoints;
  if (!points || points.length < 3) return false;
  const [rightEye, leftEye, nose] = points;
  if (!rightEye || !leftEye || !nose) return false;
  const span = Math.abs(leftEye.x - rightEye.x);
  if (!span) return false;
  return Math.abs(nose.x - (leftEye.x + rightEye.x) / 2) / span < C.WAKE_FRONTAL_MAX;
}

function tick() {
  if (!detector || !videoEl || document.hidden || videoEl.readyState < 2 || videoEl.videoWidth === 0) return;

  try {
    const now = performance.now();
    const result = detector.detectForVideo(videoEl, now);
    let largest: { originX: number; originY: number; width: number; height: number } | null = null;
    let largestDetection: Detection | null = null;
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

    const face: FaceReading | null = largest
      ? {
          x: (largest.originX + largest.width / 2) / videoEl.videoWidth,
          y: (largest.originY + largest.height / 2) / videoEl.videoHeight,
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

export const presence: PresencePort = {
  get state() {
    return currentState;
  },

  get people() {
    return lastPeople;
  },

  async init(video: HTMLVideoElement, handlers: PresenceHandlers = {}) {
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

    // The bundle is a vendored file in public/, not a dependency: the specifier
    // is held in a variable so it stays a runtime import and is never resolved
    // at build time.
    const bundleUrl = "/vendor/mediapipe/vision_bundle.mjs";
    const { FaceDetector, FilesetResolver } = (await import(/* @vite-ignore */ bundleUrl)) as {
      FaceDetector: { createFromOptions(fileset: unknown, options: unknown): Promise<typeof detector> };
      FilesetResolver: { forVisionTasks(path: string): Promise<unknown> };
    };
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
