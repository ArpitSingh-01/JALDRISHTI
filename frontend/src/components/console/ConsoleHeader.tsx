"use client";

import React from "react";
import Link from "next/link";
import { PresentableBadge } from "@/components/ui/PresentableBadge";
import { ScenarioSummary } from "@/lib/types";

export interface ConsoleHeaderProps {
  summary: ScenarioSummary;
  theme: "dark" | "light";
  onToggleTheme: () => void;
}

export const ConsoleHeader: React.FC<ConsoleHeaderProps> = ({
  summary,
  theme,
  onToggleTheme,
}) => {
  return (
    <header className="console-header">
      <div className="console-header-left">
        <Link href="/" className="brand-lockup console-brand" aria-label="JALDRISHTI Home">
          <span className="brand-deva" lang="hi">जलदृष्टि</span>
          <span className="brand-latin" style={{ fontSize: "var(--text-sm)" }}>JALDRISHTI</span>
        </Link>

        <span className="console-divider" aria-hidden="true">/</span>

        <Link href="/runs" className="console-runs-link">
          Runs
        </Link>

        <span className="console-divider" aria-hidden="true">/</span>

        <div className="console-run-meta">
          <span className="console-run-id num">{summary.run_id}</span>
          <span className="console-study-area">{summary.study_area.toUpperCase()}</span>
          <span className="console-scenario-name">({summary.scenario})</span>
        </div>
      </div>

      <div className="console-header-right">
        <PresentableBadge
          presentable={summary.honesty.presentable_as_fact}
          blockingReasons={summary.honesty.blocking_reasons}
          size="sm"
        />

        <Link
          href={`/runs/${summary.run_id}/report`}
          className="console-report-btn"
          target="_blank"
          rel="noopener noreferrer"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" width="14" height="14">
            <path d="M4 2h8a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z" />
            <path d="M6 5h4M6 8h4M6 11h2" />
          </svg>
          <span>PDF Report View</span>
        </Link>

        <button
          type="button"
          className="console-theme-toggle"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          {theme === "dark" ? "☀️ Light" : "🌙 Control Room"}
        </button>
      </div>
    </header>
  );
};
