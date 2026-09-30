document.getElementById("robotMount").innerHTML = `<svg id="robotSvg" viewBox="0 0 200 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="CampusAI robot" style="--eye:#5B6B8C">
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