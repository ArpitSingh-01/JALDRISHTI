"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

export interface UnverifiedMarkProps {
  citation?: string;
  note?: string;
  className?: string;
  children?: React.ReactNode;
}

export const UnverifiedMark: React.FC<UnverifiedMarkProps> = ({
  citation,
  note,
  className,
  children,
}) => {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <span
      className={cn("unverified-wrapper", className)}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      onFocus={() => setShowTooltip(true)}
      onBlur={() => setShowTooltip(false)}
      tabIndex={citation || note ? 0 : undefined}
      role={citation || note ? "note" : undefined}
      aria-label={citation ? `Unverified figure. Citation: ${citation}` : "Unverified figure"}
    >
      <span className="unverified-content">{children}</span>
      <span className="unverified-tag" aria-hidden="true">
        unverified
      </span>
      {showTooltip && (citation || note) && (
        <span className="unverified-tooltip" role="tooltip">
          <strong>Source not verified:</strong>
          {citation && <span className="tooltip-citation">{citation}</span>}
          {note && <span className="tooltip-note">{note}</span>}
        </span>
      )}
    </span>
  );
};
