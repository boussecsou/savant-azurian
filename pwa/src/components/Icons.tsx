/** One icon family: 24px grid, 1.6 stroke, round caps and joins, currentColor. */
const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
} as const;

export const ArrowUp = () => (
  <svg {...base} strokeWidth={2}>
    <path d="M12 19V5" />
    <path d="m6 11 6-6 6 6" />
  </svg>
);

export const Plus = () => (
  <svg {...base}>
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </svg>
);

/** Conversations: a speech bubble with a soft tail. */
export const ChatIcon = () => (
  <svg {...base}>
    <path d="M5 7.5A3.5 3.5 0 0 1 8.5 4h7A3.5 3.5 0 0 1 19 7.5v4A3.5 3.5 0 0 1 15.5 15H11l-3.4 3.1a.6.6 0 0 1-1-.45V15A3.5 3.5 0 0 1 5 11.5Z" />
  </svg>
);

/** Projects: stacked layers. */
export const Layers = () => (
  <svg {...base}>
    <path d="m12 4 8 4.2-8 4.2L4 8.2 12 4Z" />
    <path d="m4 12.2 8 4.2 8-4.2" />
    <path d="m4 16.2 8 4.2 8-4.2" />
  </svg>
);

/** Journal: a pulse line. */
export const Pulse = () => (
  <svg {...base}>
    <path d="M3 12h4l2.4-6 4.2 12 2.4-6H21" />
  </svg>
);

export const Check = () => (
  <svg {...base} width={16} height={16} strokeWidth={2.2}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
);

export const Link = () => (
  <svg {...base} width={16} height={16}>
    <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
    <path d="M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1" />
  </svg>
);

export const Clock = () => (
  <svg {...base} width={16} height={16}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </svg>
);

/** Settings: a gear with a quiet centre. Same grid and stroke as the rest of the family. */
export const Settings = () => (
  <svg {...base}>
    <circle cx="12" cy="12" r="3.1" />
    <path d="M19.2 14.6a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.56 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.56-1.11 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.56 1.03Z" />
  </svg>
);

/** A prompt and a cursor: commands on the VM. */
export const Terminal = () => (
  <svg {...base}>
    <rect x="3" y="4.5" width="18" height="15" rx="3" />
    <path d="m7.5 10 3 2.5-3 2.5" />
    <path d="M13 15h3.5" />
  </svg>
);

export const Close = () => (
  <svg {...base}>
    <path d="m6 6 12 12" />
    <path d="M18 6 6 18" />
  </svg>
);
