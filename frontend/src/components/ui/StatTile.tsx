import React from "react";
import { cn } from "@/lib/utils";
import { UnverifiedMark } from "./UnverifiedMark";

export interface StatTileProps {
  label: string;
  value: React.ReactNode;
  unit?: string;
  subtext?: string;
  unverified?: boolean;
  citation?: string;
  note?: string;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export const StatTile: React.FC<StatTileProps> = ({
  label,
  value,
  unit,
  subtext,
  unverified = false,
  citation,
  note,
  className,
  size = "md",
}) => {
  const valueContent = (
    <span className="stat-value num">
      {value}
      {unit && <span className="stat-unit">{unit}</span>}
    </span>
  );

  return (
    <div className={cn("stat-tile", `stat-tile-${size}`, className)}>
      <span className="stat-label">{label}</span>
      <div className="stat-value-container">
        {unverified ? (
          <UnverifiedMark citation={citation} note={note}>
            {valueContent}
          </UnverifiedMark>
        ) : (
          valueContent
        )}
      </div>
      {subtext && <span className="stat-subtext">{subtext}</span>}
    </div>
  );
};
