/**
 * 16 §2zp item 4(b) — a soft limiter on the microphone before the uplink.
 *
 * At Rehman's 31 Oct retest THE HOST got the words wrong when a guest held the
 * handheld microphone very close: the signal clipped, and clipped audio is
 * distorted audio, which the model transcribes as something else. Windows'
 * input gain and a guest's distance are both outside our control, so the page
 * takes the top off the signal itself.
 *
 * Below the threshold nothing is touched at all, so a normal voice is bit for
 * bit what the microphone produced. Above it the remaining headroom is
 * compressed smoothly with a tanh curve rather than cut flat — a hard clip is
 * exactly the distortion we are trying to avoid, so the curve is continuous at
 * the threshold and never reaches 1.0.
 */

/** Magnitudes above this are compressed (§2zp item 4(b)). */
export const LIMIT_THRESHOLD = 0.8;

/**
 * The highest magnitude the limiter will ever emit.
 *
 * tanh approaches 1 but in double precision reaches it exactly for a large
 * enough input, which would put a sample at full scale -- the clip this whole
 * function exists to avoid. The ceiling keeps a little headroom at the top.
 */
export const LIMIT_CEILING = 0.999;

/**
 * One sample, limited. Sign is preserved; |output| < 1 always.
 *
 * At the threshold the curve's value and slope match the straight line below
 * it, so there is no step and no kink for a sample sitting right on 0.8.
 */
export function softLimit(sample: number): number {
  if (!Number.isFinite(sample)) return 0;
  const magnitude = Math.abs(sample);
  if (magnitude <= LIMIT_THRESHOLD) return sample;
  const sign = sample < 0 ? -1 : 1;
  const headroom = 1 - LIMIT_THRESHOLD;
  // tanh maps the overshoot into the headroom: 0 -> 0 with slope 1, and it
  // approaches 1 without ever arriving, so the result stays under full scale.
  const over = (magnitude - LIMIT_THRESHOLD) / headroom;
  const limited = LIMIT_THRESHOLD + headroom * Math.tanh(over);
  return sign * Math.min(limited, LIMIT_CEILING);
}

/** What the operator's meter reports for one window (§2zp item 4(c)). */
export interface MicLevel {
  /** The largest magnitude seen, before limiting, 0.0–1.0. */
  peak: number;
  /** The percentage of samples at or above full scale, before limiting. */
  clip_pct: number;
}

/**
 * A sample at or above this counts as clipped. Not 1.0: a converter that has
 * run out of headroom returns values just under full scale, and calling only
 * exactly 1.0 a clip would report a clean signal for a badly overdriven one.
 */
export const CLIP_AT = 0.98;

/**
 * Measure a block as the microphone delivered it — before `softLimit`, because
 * the operator needs to know the signal is too hot, and the limiter's whole job
 * is to hide that from the audio.
 */
export function measure(samples: Float32Array | number[]): MicLevel {
  let peak = 0;
  let clipped = 0;
  const length = samples.length;
  for (let i = 0; i < length; i += 1) {
    const magnitude = Math.abs(samples[i] as number);
    if (magnitude > peak) peak = magnitude;
    if (magnitude >= CLIP_AT) clipped += 1;
  }
  return {
    peak: Math.min(1, peak),
    clip_pct: length ? (clipped / length) * 100 : 0,
  };
}
