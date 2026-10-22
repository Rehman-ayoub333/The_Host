/**
 * 16 §2t item 4: the Camera and Microphone drop-downs on the Start screen.
 *
 * The choice is remembered in this browser only — the TV at the stall keeps the
 * external camera and the handheld microphone it was given, across a reload,
 * without anyone touching the screen again. An empty id means the system
 * default, which is what the voice page always used.
 *
 * A browser hides device labels until it has been given permission once, so the
 * list is read again after the Start click, when the names are known.
 */
const LS_KEY = "thehost.display.devices";

export interface DeviceChoice {
  cameraId: string;
  micId: string;
}

export interface DeviceLists {
  cameras: { id: string; label: string }[];
  mics: { id: string; label: string }[];
}

export const SYSTEM_DEFAULT = "";

export function loadDeviceChoice(): DeviceChoice {
  const fallback: DeviceChoice = { cameraId: SYSTEM_DEFAULT, micId: SYSTEM_DEFAULT };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return fallback;
    const stored = JSON.parse(raw) as Partial<DeviceChoice>;
    return {
      cameraId: typeof stored.cameraId === "string" ? stored.cameraId : SYSTEM_DEFAULT,
      micId: typeof stored.micId === "string" ? stored.micId : SYSTEM_DEFAULT,
    };
  } catch {
    return fallback;
  }
}

export function saveDeviceChoice(choice: DeviceChoice) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(choice));
  } catch {
    /* a browser with storage turned off still works, it just forgets */
  }
}

export async function listDevices(): Promise<DeviceLists> {
  const empty: DeviceLists = { cameras: [], mics: [] };
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return empty;
  let devices: MediaDeviceInfo[];
  try {
    devices = await navigator.mediaDevices.enumerateDevices();
  } catch {
    return empty;
  }
  const pick = (kind: MediaDeviceKind, noun: string) =>
    devices
      .filter((device) => device.kind === kind)
      .map((device, index) => ({
        id: device.deviceId,
        // Before permission is given the label is an empty string, so the
        // drop-down still has something readable in it.
        label: device.label || `${noun} ${index + 1}`,
      }));
  return { cameras: pick("videoinput", "Camera"), mics: pick("audioinput", "Microphone") };
}

/** The id to pass to getUserMedia: undefined for the system default. */
export function deviceIdOrDefault(id: string): string | undefined {
  return id === SYSTEM_DEFAULT ? undefined : id;
}
