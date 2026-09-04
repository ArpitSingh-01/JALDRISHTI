"use client";

import React, { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export interface ScrubberProps {
  maxMinutes?: number;
  currentMinute: number;
  onChangeMinute: React.Dispatch<React.SetStateAction<number>> | ((minute: number) => void);
  className?: string;
}

export const Scrubber: React.FC<ScrubberProps> = ({
  maxMinutes = 143,
  currentMinute,
  onChangeMinute,
  className,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const togglePlay = () => {
    setIsPlaying(!isPlaying);
  };

  useEffect(() => {
    if (isPlaying) {
      playIntervalRef.current = setInterval(() => {
        (onChangeMinute as any)((prev: number) => {
          if (prev >= maxMinutes) {
            setIsPlaying(false);
            return maxMinutes;
          }
          return Math.min(maxMinutes, prev + 2);
        });
      }, 150);
    } else {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    }

    return () => {
      if (playIntervalRef.current) {
        clearInterval(playIntervalRef.current);
      }
    };
  }, [isPlaying, maxMinutes, onChangeMinute]);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number(e.target.value);
    (onChangeMinute as any)(val);
  };

  return (
    <div className={cn("scrubber-card", className)} data-motion="spatial">
      <div className="scrubber-top-row">
        <div className="scrubber-label-group">
          <span className="stat-label">TIME THRESHOLD FILTER</span>
          <span className="scrubber-title">Front Advance (from arrival time)</span>
        </div>

        <div className="scrubber-time-badge num">
          T + {Math.round(currentMinute)} min / {Math.round(maxMinutes)} min
        </div>
      </div>

      <div className="scrubber-controls-row">
        <button
          type="button"
          className="scrubber-play-btn"
          onClick={togglePlay}
          aria-label={isPlaying ? "Pause front advance" : "Play front advance animation"}
        >
          {isPlaying ? (
            <svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14">
              <rect x="3" y="2" width="3.5" height="12" rx="1" />
              <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" fill="currentColor" width="14" height="14">
              <polygon points="4,2 14,8 4,14" />
            </svg>
          )}
          <span>{isPlaying ? "Pause" : "Play Front Advance"}</span>
        </button>

        <button
          type="button"
          className="scrubber-reset-btn"
          onClick={() => {
            setIsPlaying(false);
            (onChangeMinute as any)(0);
          }}
          aria-label="Reset timeline to start"
        >
          Reset (t=0)
        </button>

        <div className="scrubber-slider-container">
          <input
            type="range"
            min="0"
            max={maxMinutes}
            value={currentMinute}
            onChange={handleSliderChange}
            className="scrubber-slider"
            aria-label="Flood front arrival time filter"
            aria-valuemin={0}
            aria-valuemax={maxMinutes}
            aria-valuenow={currentMinute}
            aria-valuetext={`Minute ${Math.round(currentMinute)} of ${Math.round(maxMinutes)}`}
          />
        </div>
      </div>

      <p className="scrubber-honesty-note">
        <strong>Honesty note:</strong> Shows where water has reached by minute <em>t</em> based on
        arrival time rasters. This is front advance, not instantaneous hydrodynamic depth replay.
      </p>
    </div>
  );
};
