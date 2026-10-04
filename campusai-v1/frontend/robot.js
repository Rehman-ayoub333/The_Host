import { C } from "./constants.js";

const STATE_COLOURS = {
  booth_off: "#5B6B8C",
  idle: "#5B6B8C",
  noticed: "#FF8A5B",
  connecting: "#3E7BFA",
  listening: "#3E7BFA",
  thinking: "#E8A33D",
  waiting_confirmation: "#37C6C0",
  speaking: "#33C481",
  error: "#E5484D",
};
const BAR_MULTIPLIERS = [0.6, 0.9, 1.0, 0.85, 0.65];
const BLINK_DURATION_MS = 160;
const PERK_DURATION_MS = 1800;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function lerp(start, end, amount) {
  return start + (end - start) * amount;
}

function randomBlinkDelay() {
  return 3000 + Math.random() * 3000;
}

export function createRobot(mountEl) {
  mountEl.innerHTML = `<svg id="robotSvg" viewBox="0 0 200 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="CampusAI robot" style="--eye:#5B6B8C">
  <g id="antenna">
    <line x1="100" y1="34" x2="100" y2="12" stroke="#3B4660" stroke-width="4" stroke-linecap="round"/>
    <circle id="antennaTip" cx="100" cy="8" r="7" fill="var(--eye)"/>
  </g>
  <rect x="18" y="92" width="14" height="44" rx="5" fill="#222B3D" stroke="#3B4660" stroke-width="2"/>
  <rect x="168" y="92" width="14" height="44" rx="5" fill="#222B3D" stroke="#3B4660" stroke-width="2"/>
  <rect x="30" y="34" width="140" height="150" rx="26" fill="#161D2B" stroke="#3B4660" stroke-width="3"/>
  <rect x="48" y="60" width="104" height="50" rx="14" fill="#0A0F18"/>
  <g id="eyes">
    <g id="eyeLeft"><g class="eye-inner">
      <circle class="eye-glow" cx="78" cy="85" r="16" fill="var(--eye)" opacity="0.22"/>
      <circle class="eye-core" cx="78" cy="85" r="10" fill="var(--eye)"/>
    </g></g>
    <g id="eyeRight"><g class="eye-inner">
      <circle class="eye-glow" cx="122" cy="85" r="16" fill="var(--eye)" opacity="0.22"/>
      <circle class="eye-core" cx="122" cy="85" r="10" fill="var(--eye)"/>
    </g></g>
  </g>
  <rect x="52" y="122" width="96" height="50" rx="10" fill="#0A0F18"/>
  <g id="mouth">
    <rect class="bar" x="59"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="77"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="95"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="113" y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="131" y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
  </g>
  <rect x="82" y="184" width="36" height="14" rx="4" fill="#2A3346"/>
  <rect x="50" y="198" width="100" height="42" rx="16" fill="#161D2B" stroke="#3B4660" stroke-width="3"/>
  <circle id="chestLed" cx="100" cy="219" r="6" fill="var(--eye)"/>
</svg>`;

  const svg = mountEl.querySelector("#robotSvg");
  const eyes = svg.querySelector("#eyes");
  const eyeInners = Array.from(svg.querySelectorAll(".eye-inner"));
  const glows = Array.from(svg.querySelectorAll(".eye-glow"));
  const bars = Array.from(svg.querySelectorAll("#mouth .bar"));
  const antenna = svg.querySelector("#antenna");
  const chestLed = svg.querySelector("#chestLed");
  for (const eye of eyeInners) {
    eye.style.transformBox = "fill-box";
    eye.style.transformOrigin = "center";
  }

  let state = "booth_off";
  let lookX = 0;
  let lookY = 0;
  let faceTarget = null;
  let lastFaceAt = 0;
  let micS = 0;
  let ampS = 0;
  let perkStart = -Infinity;
  let blinkStart = null;
  let nextBlinkAt = performance.now() + randomBlinkDelay();
  let getMicAmp = () => 0;
  let getPlaybackAmp = () => 0;
  let animationFrame = 0;

  function animate() {
    if (document.hidden) {
      animationFrame = 0;
      return;
    }

    const now = performance.now();
    const isReducedMotion = reducedMotion.matches;
    let targetX = 0;
    let targetY = 0;
    if (faceTarget && now - lastFaceAt < 1500) {
      targetX = clamp((0.5 - faceTarget.x) * 16, -6, 6);
      targetY = clamp((faceTarget.y - 0.5) * 10, -4, 4);
    } else if ((state === "idle" || state === "booth_off") && !isReducedMotion) {
      targetX = 5 * Math.sin(now / 1800);
    }
    lookX = lerp(lookX, targetX, 0.15);
    lookY = lerp(lookY, targetY, 0.15);
    eyes.setAttribute("transform", `translate(${lookX} ${lookY})`);

    let blinkScale = 1;
    if (state !== "error" && !isReducedMotion) {
      if (blinkStart === null && now >= nextBlinkAt) blinkStart = now;
      if (blinkStart !== null) {
        const progress = (now - blinkStart) / BLINK_DURATION_MS;
        if (progress >= 1) {
          blinkStart = null;
          nextBlinkAt = now + randomBlinkDelay();
        } else {
          const triangle = progress < 0.5 ? progress * 2 : (1 - progress) * 2;
          blinkScale = 1 - 0.9 * triangle;
        }
      }
    } else {
      blinkStart = null;
    }

    const pulse = state === "thinking"
      ? 0.975 + 0.125 * Math.sin((2 * Math.PI * now) / 600)
      : state === "waiting_confirmation"
        ? 0.96 + 0.08 * Math.sin((2 * Math.PI * now) / 2000)
        : 1;
    for (const eye of eyeInners) {
      eye.style.transform = `scale(${pulse}, ${pulse * blinkScale})`;
    }

    let glowRadius = 16;
    if (state === "listening") {
      micS = lerp(micS, clamp(getMicAmp(), 0, 1), 0.25);
      glowRadius = 16 + 8 * micS;
    } else if (state === "waiting_confirmation" || state === "connecting") {
      glowRadius = 16 + 8 * (0.5 + 0.5 * Math.sin((2 * Math.PI * now) / 2000));
    } else if (state === "noticed") {
      glowRadius = 19;
    }
    for (const glow of glows) glow.setAttribute("r", String(glowRadius));

    const playbackAmp = state === "speaking" ? clamp(getPlaybackAmp(), 0, 1) : 0;
    ampS = lerp(ampS, playbackAmp, 0.4);
    bars.forEach((bar, index) => {
      const height = 4 + 30 * clamp(
        ampS * BAR_MULTIPLIERS[index] * (0.75 + 0.25 * Math.sin(now / 90 + index * 1.7)),
        0,
        1,
      );
      bar.setAttribute("height", String(height));
      bar.setAttribute("y", String(166 - height));
    });

    const perkProgress = (now - perkStart) / PERK_DURATION_MS;
    let perk = 0;
    if (perkProgress >= 0 && perkProgress <= 1) {
      if (isReducedMotion) {
        perk = 1;
      } else if (perkProgress < 0.17) {
        perk = perkProgress / 0.17;
      } else if (perkProgress < 0.67) {
        perk = 1;
      } else {
        perk = 1 - (perkProgress - 0.67) / 0.33;
      }
    }
    const sway = state === "idle" && !isReducedMotion ? 2 * Math.sin(now / 1300) : 0;
    antenna.setAttribute(
      "transform",
      `translate(0 ${-6 * perk}) rotate(${-14 * perk + sway} 100 34)`,
    );
    chestLed.setAttribute("opacity", String(0.75 + 0.25 * Math.sin((2 * Math.PI * now) / 2400)));

    animationFrame = requestAnimationFrame(animate);
  }

  function onVisibilityChange() {
    if (document.hidden) {
      cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    } else if (!animationFrame) {
      animationFrame = requestAnimationFrame(animate);
    }
  }

  document.addEventListener("visibilitychange", onVisibilityChange);
  if (!document.hidden) animationFrame = requestAnimationFrame(animate);

  return {
    setState(name) {
      if (!Object.hasOwn(STATE_COLOURS, name)) return;
      state = name;
      svg.style.setProperty("--eye", STATE_COLOURS[name]);
    },
    setEyeTarget(face) {
      if (face) {
        faceTarget = face;
        lastFaceAt = performance.now();
      } else {
        faceTarget = null;
      }
    },
    perkAntenna() {
      perkStart = performance.now();
    },
    setAmplitudeSources(sources = {}) {
      getMicAmp = typeof sources.getMicAmp === "function" ? sources.getMicAmp : () => 0;
      getPlaybackAmp = typeof sources.getPlaybackAmp === "function"
        ? sources.getPlaybackAmp
        : () => 0;
    },
  };
}