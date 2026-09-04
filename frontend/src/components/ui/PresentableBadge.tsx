"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

export interface PresentableBadgeProps {
  presentable: boolean;
  blockingReasons?: string[];
  className?: string;
  size?: "sm" | "md";
}

export const PresentableBadge: React.FC<PresentableBadgeProps> = ({
  presentable,
  blockingReasons = [],
  className,
  size = "md",
}) => {
  const [isOpen, setIsOpen] = useState(false);

  if (presentable) {
    return (
      <span
        className={cn(
          "badge badge-presentable",
          `badge-${size}`,
          className
        )}
      >
        <svg
          className="badge-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="3.75 9 6.75 12 12.25 4.5" />
        </svg>
        <span>Presentable as fact</span>
      </span>
    );
  }

  return (
    <div className="badge-popover-container">
      <button
        type="button"
        className={cn(
          "badge badge-unverified-neutral",
          `badge-${size}`,
          className
        )}
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-label="Not presentable as fact. Click to view blocking reasons."
      >
        <svg
          className="badge-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="8" cy="8" r="6" />
          <line x1="8" y1="5" x2="8" y2="8" />
          <line x1="8" y1="11" x2="8.01" y2="11" />
        </svg>
        <span>Not presentable as fact ({blockingReasons.length || 1})</span>
      </button>

      {isOpen && (
        <div className="badge-popover" role="dialog" aria-label="Blocking reasons">
          <div className="badge-popover-header">
            <h4>Reasons not presentable as fact</h4>
            <button
              type="button"
              className="badge-popover-close"
              onClick={() => setIsOpen(false)}
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <p className="badge-popover-desc">
            The backend release gate flagged the following items. Output should be
            treated as planning/exercise guidance, not verified fact.
          </p>
          <ul className="badge-reasons-list">
            {blockingReasons.length > 0 ? (
              blockingReasons.map((reason, idx) => (
                <li key={idx}>{reason}</li>
              ))
            ) : (
              <li>One or more inputs are not verified against primary sources.</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
};
