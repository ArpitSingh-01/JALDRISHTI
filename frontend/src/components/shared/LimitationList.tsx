import React from "react";
import { cn } from "@/lib/utils";

export interface LimitationListProps {
  limitations: string[];
  unverifiedInputs?: string[];
  className?: string;
}

export const LimitationList: React.FC<LimitationListProps> = ({
  limitations,
  unverifiedInputs = [],
  className,
}) => {
  return (
    <div className={cn("limitations-block", className)}>
      <div className="limitations-header">
        <h4 className="limitations-title">Model Caveats & Physical Limitations</h4>
        <span className="limitations-count num">
          {limitations.length + unverifiedInputs.length} item(s) logged
        </span>
      </div>

      <div className="limitations-body prose">
        {unverifiedInputs.length > 0 && (
          <div className="unverified-group">
            <h5 className="limitations-subtitle">Unverified Input Parameters</h5>
            <ul className="limitations-list">
              {unverifiedInputs.map((item, idx) => (
                <li key={`unverified-${idx}`} className="unverified-item">
                  <span className="unverified-hatch-bullet" aria-hidden="true" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="caveats-group">
          <h5 className="limitations-subtitle">Solver & Numerical Assumptions</h5>
          <ul className="limitations-list">
            {limitations.map((item, idx) => (
              <li key={`limitation-${idx}`} className="limitation-item">
                <span className="limitation-bullet" aria-hidden="true">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};
