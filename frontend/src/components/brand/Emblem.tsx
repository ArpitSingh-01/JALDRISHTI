import React from "react";

/**
 * JALDRISHTI emblem — "Jal Chakra".
 *
 * An ORIGINAL mark: a tricolour roundel (saffron above, green below, on a
 * navy ring) enclosing a water droplet carrying a wave — the instrument
 * reading the nation's rivers. It deliberately does NOT reproduce the State
 * Emblem of India (Lion Capital), whose use by non-government entities is
 * prohibited under the State Emblem of India (Prohibition of Improper Use)
 * Act, 2005. The hues reference the flag; the composition is the project's
 * own.
 *
 * Colour values come from the design tokens where CSS allows it; SVG
 * attributes cannot resolve var() inside some build targets, so the three
 * flag hues are inlined here ONCE, mirroring design/tokens.css §1 (which
 * remains the source of truth). Change them there and here together.
 */
export const EMBLEM_SAFFRON = "#E8801A";
export const EMBLEM_GREEN = "#1B7A2E";
export const EMBLEM_NAVY = "#1F2A56";
export const EMBLEM_PAPER = "#FDFCF9";

type EmblemProps = {
  /** Rendered square size in px. Defaults to 40. */
  size?: number;
  /** Accessible label; set to "" for purely decorative use. */
  label?: string;
  className?: string;
};

export const Emblem: React.FC<EmblemProps> = ({
  size = 40,
  label = "JALDRISHTI emblem",
  className,
}) => {
  const decorative = label === "";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role={decorative ? "presentation" : "img"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative || undefined}
      className={className}
      focusable="false"
    >
      {!decorative && (
        <title>{label}</title>
      )}

      {/* Outer navy ring */}
      <circle cx="24" cy="24" r="22" stroke={EMBLEM_NAVY} strokeWidth="2.5" />

      {/* Tricolour arcs: saffron over green, white field between */}
      <path
        d="M 8.4 24 A 15.6 15.6 0 0 1 39.6 24"
        stroke={EMBLEM_SAFFRON}
        strokeWidth="4.5"
        strokeLinecap="round"
      />
      <path
        d="M 39.6 24 A 15.6 15.6 0 0 1 8.4 24"
        stroke={EMBLEM_GREEN}
        strokeWidth="4.5"
        strokeLinecap="round"
      />

      {/* Water droplet */}
      <path
        d="M24 14.5 C 28.8 20.6, 31 24.2, 31 27.8 A 7 7 0 1 1 17 27.8
           C 17 24.2, 19.2 20.6, 24 14.5 Z"
        fill={EMBLEM_NAVY}
      />
      {/* Wave inside the droplet */}
      <path
        d="M 19.6 28.6 q 2.2 -2.1 4.4 0 t 4.4 0"
        stroke={EMBLEM_PAPER}
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
};
