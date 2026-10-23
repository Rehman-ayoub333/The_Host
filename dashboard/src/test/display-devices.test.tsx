/**
 * 16 §2u item 5: the display's camera and microphone, chosen on the laptop.
 *
 * The two drop-downs moved off the TV and into the dashboard's Settings. What
 * matters here is that Settings writes where `/display` reads, and that a saved
 * device which has gone missing is reported to the operator -- never on the TV,
 * which silently falls back to the system default.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/agent/service", () => ({
  connectAgent: () => undefined,
  disconnectAgent: () => undefined,
  getAgentConfig: () => ({ agentUrl: "http://localhost:8000", token: "" }),
  saveAgentConfig: () => undefined,
  retryConnection: () => Promise.resolve(null),
  pauseHost: () => Promise.resolve(null),
  resumeHost: () => Promise.resolve(null),
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (config: unknown) => config,
  useNavigate: () => () => Promise.resolve(),
  Link: ({ children }: { children?: unknown }) => children,
  useRouterState: () => ({ location: { pathname: "/settings" } }),
}));

import { SettingsPage } from "@/routes/settings";
import {
  loadDeviceChoice,
  missingDeviceNotes,
  saveDeviceChoice,
  SYSTEM_DEFAULT,
  type DeviceLists,
} from "@/lib/booth/devices";

const LISTS: DeviceLists = {
  cameras: [{ id: "cam-a", label: "Logitech C920" }],
  mics: [{ id: "mic-a", label: "Handheld" }],
};

describe("a saved device that has gone missing (16 §2u item 5)", () => {
  it("says nothing when the system default is in use", () => {
    expect(missingDeviceNotes({ cameraId: SYSTEM_DEFAULT, micId: SYSTEM_DEFAULT }, LISTS)).toEqual([]);
  });

  it("says nothing when both saved devices are present", () => {
    expect(missingDeviceNotes({ cameraId: "cam-a", micId: "mic-a" }, LISTS)).toEqual([]);
  });

  it("names the camera that is gone", () => {
    expect(missingDeviceNotes({ cameraId: "cam-gone", micId: "mic-a" }, LISTS)).toEqual(["Saved camera not found"]);
  });

  it("names the microphone that is gone", () => {
    expect(missingDeviceNotes({ cameraId: "cam-a", micId: "mic-gone" }, LISTS)).toEqual(["Saved microphone not found"]);
  });

  it("names both when both are gone", () => {
    expect(missingDeviceNotes({ cameraId: "cam-gone", micId: "mic-gone" }, LISTS)).toEqual([
      "Saved camera not found",
      "Saved microphone not found",
    ]);
  });

  it("reports nothing when the browser cannot see any device yet", () => {
    // An empty list is "permission not given", not "the device is missing".
    expect(missingDeviceNotes({ cameraId: "cam-a", micId: "mic-a" }, { cameras: [], mics: [] })).toEqual([]);
  });
});

describe("what Settings saves is what /display reads (16 §2u item 5)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a choice through the one storage key both screens use", () => {
    saveDeviceChoice({ cameraId: "cam-a", micId: "mic-a" });

    expect(loadDeviceChoice()).toEqual({ cameraId: "cam-a", micId: "mic-a" });
  });

  it("falls back to the system default when nothing has been chosen", () => {
    expect(loadDeviceChoice()).toEqual({ cameraId: SYSTEM_DEFAULT, micId: SYSTEM_DEFAULT });
  });
});

describe("the Display screen devices section (16 §2u item 5)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          { kind: "videoinput", deviceId: "cam-a", label: "Logitech C920" },
          { kind: "audioinput", deviceId: "mic-a", label: "Handheld" },
        ],
      },
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("is on the Settings screen, with a camera and a microphone drop-down", async () => {
    render(<SettingsPage />);

    expect(await screen.findByText("Display screen devices")).toBeInTheDocument();
    expect(screen.getByLabelText("Camera")).toBeInTheDocument();
    expect(screen.getByLabelText("Microphone")).toBeInTheDocument();
  });

  it("offers the system default on both", () => {
    render(<SettingsPage />);

    expect(screen.getByLabelText("Camera")).toHaveValue(SYSTEM_DEFAULT);
    expect(screen.getByLabelText("Microphone")).toHaveValue(SYSTEM_DEFAULT);
  });

  it("takes its slot in the grid, rather than collapsing to one column", async () => {
    // PanelBoundary hands the panel its grid class as a prop (PanelBoundary.tsx),
    // so a panel that does not forward className renders one column wide. That
    // is exactly what happened to this section the first time.
    render(<SettingsPage />);

    const heading = await screen.findByText("Display screen devices");
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    expect(section!.className).toContain("col-span-");
  });

  it("warns the operator about a saved device that is gone", async () => {
    saveDeviceChoice({ cameraId: "cam-unplugged", micId: "mic-a" });

    render(<SettingsPage />);

    expect(await screen.findByText(/Saved camera not found/)).toBeInTheDocument();
    expect(screen.queryByText(/Saved microphone not found/)).toBeNull();
  });
});
