export const C = {
  // 16 section 2i item 3: eight minutes, and the cap is now a polite wrap-up
  // rather than a cut, so the grace that follows it is far longer than before.
  AUTO_RESET_MS: 45000, MAX_SESSION_MS: 480000, ERROR_AUTO_RECOVER_MS: 15000,
  DETECT_INTERVAL_MS: 400, ARRIVAL_CONSECUTIVE: 3, ABSENCE_MS: 6000,
  MIN_FACE_WIDTH_RATIO: 0.08, MIN_DETECTION_CONFIDENCE: 0.6, GREET_COOLDOWN_MS: 45000,
  SNAPSHOT_WIDTH: 640, SNAPSHOT_HEIGHT: 480, SNAPSHOT_QUALITY: 0.85,
  MIC_BUFFER_SIZE: 4096, INPUT_SAMPLE_RATE: 16000, OUTPUT_SAMPLE_RATE: 24000,
  AGENT_LABEL: "THE HOST", VISION_REPORT_MS: 2000,
  VOICE_POLL_MS: 100, VOICE_ACTIVE_LEVEL: 0.15, VOICE_ON_POLLS: 2, VOICE_OFF_MS: 800,
  CAP_GRACE_MS: 90000,
  // 16 section 2h item 2: wake on speech needs a face that is close AND looking
  // at the screen, because sound alone cannot tell a guest from nearby chatter.
  // 2h item 9: these three start values stand until Rehman measures them.
  WAKE_MIN_FACE_RATIO: 0.14, WAKE_FRONTAL_MAX: 0.35,
  WAKE_SPEECH_MS: 600, WAKE_AFTER_END_MS: 3000,
  // 16 section 2h item 4: stop talking to an empty room.
  NO_FACE_END_MS: 20000,
  // 16 section 2i item 6: the booth screen is public, so a guest's own words are
  // not printed where the next guest can read them. THE HOST's lines still show.
  SHOW_GUEST_TRANSCRIPT: false,
};
