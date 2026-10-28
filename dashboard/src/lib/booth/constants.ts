/**
 * 16 §2t item 3: the old booth page's constants, ported with the same values.
 *
 * Every number here was measured at the booth or decided in a spec section, and
 * the comments say which. Nothing is re-tuned by the port: /display is meant to
 * behave exactly as `booth/` does, so a value that changes here changes
 * behaviour Rehman has already tested.
 */
export const C = {
  // 16 §2i item 3: eight minutes, and the cap is now a polite wrap-up
  // rather than a cut, so the grace that follows it is far longer than before.
  AUTO_RESET_MS: 45000,
  MAX_SESSION_MS: 480000,
  ERROR_AUTO_RECOVER_MS: 15000,
  DETECT_INTERVAL_MS: 400,
  ARRIVAL_CONSECUTIVE: 3,
  ABSENCE_MS: 6000,
  MIN_FACE_WIDTH_RATIO: 0.08,
  MIN_DETECTION_CONFIDENCE: 0.6,
  GREET_COOLDOWN_MS: 45000,
  SNAPSHOT_WIDTH: 640,
  SNAPSHOT_HEIGHT: 480,
  SNAPSHOT_QUALITY: 0.85,
  // 16 §2r item 4: one microphone frame, about 100 ms at 16 kHz.
  MIC_FRAME_SAMPLES: 1600,
  INPUT_SAMPLE_RATE: 16000,
  OUTPUT_SAMPLE_RATE: 24000,
  AGENT_LABEL: "THE HOST",
  VISION_REPORT_MS: 2000,
  // 16 §2j item 7: measured at the booth, not guessed. Quiet idle runs
  // 0.00-0.05 and speech into the handheld mic 0.4-1.0, so 0.20 sits well clear
  // of the room and well under a guest.
  VOICE_POLL_MS: 100,
  VOICE_ACTIVE_LEVEL: 0.2,
  VOICE_ON_POLLS: 2,
  VOICE_OFF_MS: 800,
  CAP_GRACE_MS: 90000,
  // 16 §2h item 2: wake on speech needs a face that is close AND looking
  // at the screen, because sound alone cannot tell a guest from nearby chatter.
  // 2j item 7: a face at the counter measured 0.25-0.36 wide and frontal, so
  // 0.18 admits the guest standing there and not the queue behind them.
  WAKE_MIN_FACE_RATIO: 0.18,
  WAKE_FRONTAL_MAX: 0.35,
  WAKE_SPEECH_MS: 600,
  WAKE_AFTER_END_MS: 3000,
  // 16 §2h item 4: stop talking to an empty room.
  NO_FACE_END_MS: 20000,
  // 16 §2i item 6: the screen is public, so a guest's own words are never
  // printed where the next guest can read them. 2t item 4 shows THE HOST's
  // caption on the TV; this flag still governs the guest's side, and on a
  // guest-facing TV it is never turned on.
  SHOW_GUEST_TRANSCRIPT: false,
  // 16 §2j item 3: a conversation that is still being cleaned up refuses
  // the next one for a moment, and at the gala nobody should see an error for
  // that. Three quiet retries, then the refusal is shown like any other.
  BUSY_RETRY_LIMIT: 3,
  BUSY_RETRY_MS: 1500,
  // 16 §2k item 3: what the guest sees while the backend rebuilds a
  // dropped connection. The backend keeps trying for 30 s, so none of the
  // page's own clocks may run out underneath it.
  RECONNECTING_LABEL: "Reconnecting…",
  // 16 §2t item 4: the wait is always visibly alive. The orb goes to THINKING
  // the moment the guest stops speaking, and if THE HOST has still not started
  // talking this long afterwards the caption says so.
  ONE_MOMENT_MS: 3000,
  ONE_MOMENT_LABEL: "One moment…",
  // 16 §2u item 3: THE HOST never hears itself. At the gala its voice comes out
  // of the TV or the laptop speakers, close to the handheld microphone, and with
  // start-of-speech sensitivity HIGH (§2r item 5) its own voice coming back was
  // being taken for a guest starting to talk. While its audio is playing, and
  // for this long after, the page sends silence instead of the microphone and
  // its own voice-activity detection ignores the window.
  ECHO_GATE_TAIL_MS: 300,
  // 16 §2u item 4: playback never starves. A chunk that can only be scheduled
  // more than this long after the previous chunk of the same turn finished is an
  // underrun -- a gap the guest hears as THE HOST's voice breaking up.
  PLAYBACK_UNDERRUN_MS: 150,
  // 16 §2u item 4: the caption is rewritten at most 10 times a second, so a
  // fast run of transcript fragments cannot turn into a React render per
  // fragment while audio is being scheduled.
  CAPTION_MIN_MS: 100,
  // 16 §2zf item 7, Rehman's request 2(d): THE HOST's words disappear from the
  // TV once they have been said. The caption stays up while the audio plays
  // out and for this long afterwards, so the guest can read the end of a line
  // they only half heard; then the screen is clear again. Only the
  // ready-order banners stay on their own 15 s clock.
  CAPTION_CLEAR_MS: 1500,
  // How often the page looks to see whether the queued audio has finished.
  // A turn ends at the backend long before its last chunk is heard, so the
  // 1.5 s is counted from the end of playback, not the end of the turn.
  CAPTION_CLEAR_POLL_MS: 100,
} as const;

/** 16 §2i item 3: how long after the wrap-up line is asked for the page waits
 * before it may end the conversation. */
export const WRAP_UP_SETTLE_MS = 3000;

/** 16 §2j item 3: the one refusal that is retried quietly instead of shown. */
export const BUSY_REFUSAL = "Another conversation is already active.";

/** 16 §2r item 2(a): one counter line every 5 s with ?debug=mic. */
export const MIC_COUNTER_MS = 5000;
export const LONGTASK_MS = 50;
export const MIC_DEBUG_WINDOW_MS = 5000;
export const MIC_DEBUG_PRINT_MS = 500;
