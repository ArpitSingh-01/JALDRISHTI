import type { Metadata } from "next";
import { bricolageGrotesque, publicSans, ibmPlexMono } from "@/lib/fonts";
import "@fontsource/ibm-plex-sans-devanagari/400.css";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "JALDRISHTI — Dam-Break Flood Simulation",
  description:
    "Dam-break and river-blockage flood simulation that tells you who has to move, and when. Smart India Hackathon 2026, PS 26161, NTRO.",
  keywords: [
    "dam break",
    "flood simulation",
    "inundation modelling",
    "JALDRISHTI",
    "SIH 2026",
    "NTRO",
    "disaster management",
    "hydrodynamic modelling",
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${bricolageGrotesque.variable} ${publicSans.variable} ${ibmPlexMono.variable}`}
    >
      <head>
        <meta name="theme-color" content="#FF9933" />
      </head>
      <body>{children}</body>
    </html>
  );
}
