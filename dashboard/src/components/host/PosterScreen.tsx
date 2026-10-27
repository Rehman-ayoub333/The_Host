import { useEffect, useState } from "react";

/** One poster at a time, 8 s each, with a 0.6 s cross-fade (16 §2ze item 5). */
export const POSTER_MS = 8000;
export const POSTER_FADE_MS = 600;

/**
 * The TV's idle screen: Rehman's own full-screen pictures, and nothing else.
 *
 * Rehman's rule (16 §2ze item 2(d)) is that each picture already carries all
 * its information, so this renders no text, no logo, no caption and no control
 * — every poster is an `<img>` with an empty `alt`, and the whole layer is
 * `aria-hidden`. The pictures are stacked and cross-faded by opacity rather
 * than swapped, so the outgoing one fades out as the next fades in instead of
 * the screen flashing the background colour between them.
 *
 * `object-contain` on the display's own background colour means a picture that
 * is not exactly 1920×1080 is letterboxed rather than cropped.
 */
export function PosterScreen({ posters }: { posters: string[] }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (posters.length < 2) return;
    const t = setInterval(() => setIndex((i) => (i + 1) % posters.length), POSTER_MS);
    return () => clearInterval(t);
  }, [posters.length]);

  if (posters.length === 0) return null;
  const current = index % posters.length;

  return (
    <div data-testid="poster-screen" aria-hidden="true" className="absolute inset-0 bg-background">
      {posters.map((src, i) => (
        <img
          key={src}
          src={src}
          alt=""
          data-testid="poster"
          data-current={i === current ? "true" : "false"}
          className="absolute inset-0 h-full w-full object-contain transition-opacity ease-in-out"
          style={{ opacity: i === current ? 1 : 0, transitionDuration: `${POSTER_FADE_MS}ms` }}
        />
      ))}
    </div>
  );
}
