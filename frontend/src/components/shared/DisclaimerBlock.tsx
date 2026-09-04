import React from "react";
import { MODEL_DISCLAIMER } from "@/lib/constants";
import { cn } from "@/lib/utils";

export interface DisclaimerBlockProps {
  className?: string;
  compact?: boolean;
}

export const DisclaimerBlock: React.FC<DisclaimerBlockProps> = ({
  className,
  compact = false,
}) => {
  return (
    <div
      className={cn(
        "disclaimer-card",
        compact && "disclaimer-compact",
        className
      )}
      role="note"
      aria-label="Statutory and Model Disclaimer"
    >
      <div className="disclaimer-header">
        <svg
          className="disclaimer-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="8" cy="8" r="6.5" />
          <line x1="8" y1="5" x2="8" y2="8" />
          <line x1="8" y1="11" x2="8.01" y2="11" />
        </svg>
        <span className="disclaimer-title">STATUTORY & MODEL DISCLAIMER</span>
      </div>
      <p className="disclaimer-body prose">{MODEL_DISCLAIMER}</p>
    </div>
  );
};
