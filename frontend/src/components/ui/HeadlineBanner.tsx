"use client";

import React, { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export interface HeadlineBannerProps {
  headline: string;
  floodedAreaKm2?: number;
  reportedPopulation?: number;
  firstArrivalMin?: number | null;
  className?: string;
  animate?: boolean;
}

export const HeadlineBanner: React.FC<HeadlineBannerProps> = ({
  headline,
  floodedAreaKm2,
  reportedPopulation,
  firstArrivalMin,
  className,
  animate = true,
}) => {
  const [displayedPop, setDisplayedPop] = useState(animate ? 0 : reportedPopulation || 0);
  const [displayedArea, setDisplayedArea] = useState(animate ? 0 : floodedAreaKm2 || 0);

  useEffect(() => {
    if (!animate) {
      if (reportedPopulation) setDisplayedPop(reportedPopulation);
      if (floodedAreaKm2) setDisplayedArea(floodedAreaKm2);
      return;
    }

    const duration = 600; // --dur-4
    const steps = 30;
    const intervalTime = duration / steps;
    let step = 0;

    const timer = setInterval(() => {
      step++;
      const progress = Math.min(1, step / steps);
      // Ease out cubic
      const ease = 1 - Math.pow(1 - progress, 3);

      if (reportedPopulation) {
        setDisplayedPop(Math.round(reportedPopulation * ease));
      }
      if (floodedAreaKm2) {
        setDisplayedArea(Number((floodedAreaKm2 * ease).toFixed(1)));
      }

      if (progress >= 1) {
        clearInterval(timer);
      }
    }, intervalTime);

    return () => clearInterval(timer);
  }, [animate, reportedPopulation, floodedAreaKm2]);

  return (
    <div className={cn("headline-banner", className)}>
      <div className="headline-badge-row">
        <span className="headline-tag">DECISION SUMMARY</span>
        {firstArrivalMin !== undefined && (
          <span className="headline-time-pill num">
            {firstArrivalMin === null
              ? "Not reached"
              : `First arrival in ${Math.round(firstArrivalMin)} min`}
          </span>
        )}
      </div>

      <h2 className="headline-text">{headline}</h2>

      {(reportedPopulation !== undefined || floodedAreaKm2 !== undefined) && (
        <div className="headline-metrics-strip">
          {floodedAreaKm2 !== undefined && (
            <div className="headline-metric-box">
              <span className="headline-metric-val num">
                {displayedArea >= 10
                  ? Math.round(displayedArea).toLocaleString()
                  : displayedArea.toFixed(1)}
              </span>
              <span className="headline-metric-lbl">km² new inundation</span>
            </div>
          )}
          {reportedPopulation !== undefined && (
            <div className="headline-metric-box">
              <span className="headline-metric-val num">
                {displayedPop.toLocaleString()}
              </span>
              <span className="headline-metric-lbl">people exposed</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
