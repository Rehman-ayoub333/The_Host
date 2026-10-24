/**
 * 16 §2t items 3 and 4: the React side of `HostSession`.
 *
 * The session itself is framework-free and lives for as long as the route does.
 * This hook only creates it, subscribes to it, and tears it down — so the rules
 * stay testable without React, and the page stays a view of them.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getAgentConfig } from "@/lib/agent/service";
import { audio } from "./audio";
import { presence } from "./presence";
import { HostSession, type SessionView, type SocketLike, type StartOptions } from "./session";

/** ?debug=mic — the counters, the level readout and the text box (§2g item 5). */
export function isMicDebug(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("debug") === "mic";
}

export function useHostSession() {
  const ref = useRef<HostSession | null>(null);
  const [started, setStarted] = useState(false);

  if (!ref.current && typeof window !== "undefined") {
    ref.current = new HostSession({
      audio,
      presence,
      // 16 §2t item 3: the page connects to the configured agent link's host,
      // not to its own: the dashboard is served from :8080, the backend is :8000.
      agentUrl: getAgentConfig().agentUrl,
      debugMic: isMicDebug(),
      createSocket: (url: string) => new WebSocket(url) as unknown as SocketLike,
      now: () => Date.now(),
    });
  }

  const session = ref.current;

  const view = useSyncExternalStore<SessionView>(
    useCallback((listener: () => void) => (session ? session.subscribe(listener) : () => {}), [session]),
    () => session?.getView() ?? FALLBACK_VIEW,
    () => FALLBACK_VIEW,
  );

  useEffect(() => {
    if (!session) return;
    // The page being closed must take the microphone, the camera and the socket
    // with it, exactly as the old booth page's beforeunload did.
    const onUnload = () => session.destroy();
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      session.destroy();
    };
  }, [session]);

  const start = useCallback(
    async (options: StartOptions) => {
      if (!session) return;
      await session.start(options);
      setStarted(true);
    },
    [session],
  );

  return { session, view, started, start };
}

const FALLBACK_VIEW: SessionView = {
  state: "booth_off",
  reconnecting: false,
  errorMessage: "",
  hostLine: "",
  oneMoment: false,
  micAvailable: false,
  cameraAvailable: false,
  presenceAvailable: false,
  notes: [],
};
