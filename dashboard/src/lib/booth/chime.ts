/**
 * 16 §2v item 3: the soft chime that replaces the browser's voice.
 *
 * THE HOST has one voice, and it is Gemini's. When an order becomes ready
 * between conversations there is nobody to speak, so the TV shows the ready
 * banner and plays this: a short, gentle two-note chime made here with Web
 * Audio. No audio file, and no words -- the words were the bug (§2v item 1,
 * where a Windows voice announced an order THE HOST had already announced).
 *
 * The chime keeps its own AudioContext. `audio.ts` only has one while a
 * conversation is running, and this sound exists precisely for when none is.
 */

/** About 0.6 s, as §2v item 3 asks. */
export const CHIME_MS = 600;
/** Gentle: a peak well below THE HOST's own voice, which plays at full gain. */
export const CHIME_PEAK_GAIN = 0.08;
/** Two partials a fifth apart: a doorbell, not an alarm. */
export const CHIME_HZ = [880, 1320] as const;

export interface ChimePort {
  /** Plays one chime. Never throws: a missed chime is not worth a crash. */
  play(): void;
}

type ContextMaker = () => AudioContext;

function defaultMaker(): AudioContext {
  return new AudioContext();
}

/**
 * The real chime. Exported as a factory so the unit tests can hand it a fake
 * AudioContext and read back every node it builds.
 *
 * The context belongs to the port, not to the module: one per port, made on the
 * first chime and reused after that. A module-level one would be shared by
 * every port ever created, which is wrong for the tests and pointless here --
 * the page makes exactly one port.
 */
export function createChime(makeContext: ContextMaker = defaultMaker): ChimePort {
  let ctx: AudioContext | null = null;

  return {
    play() {
      try {
        if (!ctx) ctx = makeContext();
        // A context created before the guest has tapped the screen starts
        // suspended; the tap resumes it, and until then there is nothing to
        // hear anyway. Best-effort, like the rest of this function.
        void ctx.resume?.();
        const now = ctx.currentTime;
        const seconds = CHIME_MS / 1000;
        const master = ctx.createGain();
        // One short attack, then an exponential tail to silence. Ramping to a
        // small positive value rather than 0 because exponentialRampToValueAtTime
        // cannot reach zero.
        master.gain.setValueAtTime(0.0001, now);
        master.gain.exponentialRampToValueAtTime(CHIME_PEAK_GAIN, now + 0.02);
        master.gain.exponentialRampToValueAtTime(0.0001, now + seconds);
        master.connect(ctx.destination);

        for (const hz of CHIME_HZ) {
          const osc = ctx.createOscillator();
          osc.type = "sine";
          osc.frequency.setValueAtTime(hz, now);
          osc.connect(master);
          osc.start(now);
          osc.stop(now + seconds);
        }
      } catch {
        /* the chime is best-effort: the banner is what the guest reads */
      }
    },
  };
}

export const chime: ChimePort = createChime();
