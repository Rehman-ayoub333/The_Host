/**
 * 16 §2zp item 4(b) and 4(c) — the soft limiter and the level it reports.
 *
 * At Rehman's 31 Oct retest THE HOST got the words wrong when a guest held the
 * handheld microphone very close: the signal clipped, and clipped audio is
 * distorted audio. A hard clip is the distortion itself, so what matters here
 * is that the curve is smooth, never reaches full scale, and leaves a normal
 * voice completely alone.
 */
import { describe, expect, it } from "vitest";
import { CLIP_AT, LIMIT_THRESHOLD, measure, softLimit } from "@/lib/booth/limiter";

describe("the soft limiter (16 §2zp item 4b)", () => {
  it("leaves everything at or below the threshold bit for bit", () => {
    for (const sample of [0, 0.01, 0.25, 0.5, 0.79, LIMIT_THRESHOLD, -0.5, -LIMIT_THRESHOLD]) {
      expect(softLimit(sample)).toBe(sample);
    }
  });

  it("compresses above the threshold instead of cutting flat", () => {
    const limited = softLimit(0.95);
    // Reduced, but not to the threshold and not to a flat ceiling.
    expect(limited).toBeLessThan(0.95);
    expect(limited).toBeGreaterThan(LIMIT_THRESHOLD);
  });

  it("never reaches or passes full scale, however hot the input", () => {
    for (const sample of [0.9, 1, 1.5, 4, 100]) {
      expect(Math.abs(softLimit(sample))).toBeLessThan(1);
      expect(Math.abs(softLimit(-sample))).toBeLessThan(1);
    }
  });

  it("keeps the sign", () => {
    expect(softLimit(-0.95)).toBeLessThan(0);
    expect(softLimit(0.95)).toBeGreaterThan(0);
    expect(softLimit(-0.95)).toBeCloseTo(-softLimit(0.95), 12);
  });

  it("is continuous at the threshold, so there is no step to hear", () => {
    const below = softLimit(LIMIT_THRESHOLD - 1e-6);
    const above = softLimit(LIMIT_THRESHOLD + 1e-6);
    expect(Math.abs(above - below)).toBeLessThan(1e-5);
  });

  it("rises monotonically, so louder in is never quieter out", () => {
    let previous = -Infinity;
    for (let sample = 0; sample <= 2; sample += 0.01) {
      const limited = softLimit(sample);
      expect(limited).toBeGreaterThanOrEqual(previous);
      previous = limited;
    }
  });

  it("treats a broken sample as silence rather than passing NaN to the uplink", () => {
    expect(softLimit(Number.NaN)).toBe(0);
    expect(softLimit(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe("the level the meter reports (16 §2zp item 4c)", () => {
  it("reports the peak magnitude of the block", () => {
    expect(measure([0, 0.2, -0.6, 0.35]).peak).toBeCloseTo(0.6, 10);
  });

  it("reports nothing clipped for a normal voice", () => {
    expect(measure([0.1, -0.3, 0.45, -0.2]).clip_pct).toBe(0);
  });

  it("counts the clipped samples as a percentage", () => {
    // Two of eight at full scale.
    const level = measure([1, -1, 0.1, 0.2, 0.3, 0.1, 0, 0]);
    expect(level.clip_pct).toBeCloseTo(25, 10);
    expect(level.peak).toBe(1);
  });

  it("counts a sample just under full scale as clipped", () => {
    // A converter out of headroom returns values a shade under 1.0; calling
    // only exactly 1.0 a clip would report a clean signal for a hot one.
    expect(measure([CLIP_AT]).clip_pct).toBe(100);
    expect(measure([CLIP_AT - 0.01]).clip_pct).toBe(0);
  });

  it("handles an empty block without dividing by zero", () => {
    expect(measure([])).toEqual({ peak: 0, clip_pct: 0 });
  });

  it("measures before limiting, which is the whole point", () => {
    // The operator has to be told the signal is too hot; the limiter's job is
    // to keep that out of the audio, not out of the meter.
    const raw = [1, 1, 1, 1];
    expect(measure(raw).clip_pct).toBe(100);
    expect(measure(raw.map(softLimit)).clip_pct).toBe(0);
  });
});
