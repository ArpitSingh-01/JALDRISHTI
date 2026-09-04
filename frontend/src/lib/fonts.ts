/**
 * Self-hosted font configuration via next/font.
 *
 * Downloads at build time, serves from the same origin — works behind
 * captive portals and bad venue networks. See frontend.md §2.4.
 *
 * Four voices:
 *   Bricolage Grotesque — display/headings (roman only; italic banned)
 *   Public Sans — body + UI (deliberately NOT Inter)
 *   IBM Plex Mono — every number that means something (tabular figures)
 *   IBM Plex Sans Devanagari — script extension for "जलदृष्टि"
 */

import {
  Bricolage_Grotesque,
  Public_Sans,
  IBM_Plex_Mono,
} from "next/font/google";
import localFont from "next/font/local";

export const bricolageGrotesque = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
  variable: "--font-display",
  fallback: ["Public Sans", "system-ui", "sans-serif"],
});

export const publicSans = Public_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-body",
  fallback: ["system-ui", "-apple-system", "sans-serif"],
});

export const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-mono",
  fallback: ["ui-monospace", "Cascadia Mono", "monospace"],
});

// IBM Plex Sans Devanagari is not in next/font/google's typed catalog for
// all versions. We use @fontsource as a fallback — it is installed as an
// npm package and bundled at build time, same offline guarantee.
// Import in layout.tsx: import "@fontsource/ibm-plex-sans-devanagari/400.css"
