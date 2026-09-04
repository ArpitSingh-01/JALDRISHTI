import React from "react";
import {
  DEFRA_CLASS_NAMES,
  DEFRA_CLASS_COLOURS,
  DEFRA_CLASS_MEANINGS,
  AIDR_CLASS_NAMES,
  AIDR_CLASS_COLOURS,
  ARRIVAL_BAND_LABELS,
  ARRIVAL_BAND_COLOURS,
  PRE_EXISTING_WATER_COLOUR,
} from "@/lib/ramps.generated";
import { cn } from "@/lib/utils";

export type LegendType = "arrival" | "defra" | "aidr" | "depth" | "speed" | "dv";

export interface LegendProps {
  type: LegendType;
  areaBreakdown?: Record<string, number>;
  activeBand?: string | number | null;
  onSelectBand?: (band: string | number) => void;
  className?: string;
  compact?: boolean;
}

export const Legend: React.FC<LegendProps> = ({
  type,
  areaBreakdown,
  activeBand,
  onSelectBand,
  className,
  compact = false,
}) => {
  let title = "";
  let description = "";
  let items: Array<{
    id: string | number;
    label: string;
    colour: string;
    sublabel?: string;
    area?: number;
  }> = [];

  switch (type) {
    case "arrival":
      title = "Arrival Time (Isochrones)";
      description = "Fastest arrival is darkest. Measured from failure onset.";
      items = ARRIVAL_BAND_LABELS.map((label, idx) => ({
        id: idx,
        label,
        colour: ARRIVAL_BAND_COLOURS[idx],
        area: areaBreakdown ? areaBreakdown[label] : undefined,
      }));
      items.push({
        id: -2,
        label: "Pre-existing water",
        colour: PRE_EXISTING_WATER_COLOUR,
        sublabel: "Reservoir / channel",
      });
      break;

    case "defra":
      title = "DEFRA / EA Hazard Rating";
      description = "HR = d × (v + 0.5) + DF (UK Environment Agency standard)";
      items = DEFRA_CLASS_NAMES.map((name, idx) => ({
        id: name,
        label: name,
        colour: DEFRA_CLASS_COLOURS[idx],
        sublabel: DEFRA_CLASS_MEANINGS[idx],
        area: areaBreakdown ? areaBreakdown[name] : undefined,
      }));
      break;

    case "aidr":
      title = "AIDR / AR&R Hazard Classification";
      description = "Australian Institute for Disaster Resilience (H1 to H6)";
      items = AIDR_CLASS_NAMES.map((name, idx) => ({
        id: name,
        label: name,
        colour: AIDR_CLASS_COLOURS[idx],
        area: areaBreakdown ? areaBreakdown[name] : undefined,
      }));
      break;

    case "depth":
      title = "Peak Water Depth";
      description = "Maximum inundation depth throughout simulation.";
      items = [
        { id: "0-1", label: "< 1.0 m", colour: "#bdd7e7" },
        { id: "1-2", label: "1.0 – 2.0 m", colour: "#6baed6" },
        { id: "2-5", label: "2.0 – 5.0 m", colour: "#3182bd" },
        { id: "5-10", label: "5.0 – 10.0 m", colour: "#08519c" },
        { id: ">10", label: "> 10.0 m", colour: "#08306b" },
      ];
      break;

    case "speed":
      title = "Peak Flow Velocity";
      description = "Maximum velocity reached during flood wave progression.";
      items = [
        { id: "0-1", label: "< 1.0 m/s", colour: "#e5f5f9" },
        { id: "1-2", label: "1.0 – 2.0 m/s", colour: "#99d8c9" },
        { id: "2-5", label: "2.0 – 5.0 m/s", colour: "#41ae76" },
        { id: "5-10", label: "5.0 – 10.0 m/s", colour: "#238b45" },
        { id: ">10", label: "> 10.0 m/s", colour: "#00441b" },
      ];
      break;

    case "dv":
      title = "Peak Depth × Velocity (d × v)";
      description = "Momentum surrogate for structural impact assessment.";
      items = [
        { id: "0-0.5", label: "< 0.5 m²/s", colour: "#ffeda0" },
        { id: "0.5-1.5", label: "0.5 – 1.5 m²/s", colour: "#feb24c" },
        { id: "1.5-3.0", label: "1.5 – 3.0 m²/s", colour: "#f03b20" },
        { id: ">3.0", label: "> 3.0 m²/s", colour: "#7f0000" },
      ];
      break;
  }

  return (
    <div className={cn("legend-panel", compact && "legend-compact", className)}>
      <div className="legend-header">
        <h4 className="legend-title">{title}</h4>
        {!compact && description && (
          <p className="legend-desc">{description}</p>
        )}
      </div>

      <div className="legend-items" role="list">
        {items.map((item) => {
          const isSelected = activeBand !== undefined && activeBand === item.id;
          return (
            <div
              key={String(item.id)}
              className={cn(
                "legend-row",
                isSelected && "legend-row-active",
                onSelectBand && "legend-row-clickable"
              )}
              onClick={() => onSelectBand && onSelectBand(item.id)}
              role="listitem"
            >
              <span
                className="legend-swatch"
                style={{ backgroundColor: item.colour }}
                aria-hidden="true"
              />
              <div className="legend-row-text">
                <span className="legend-label">{item.label}</span>
                {item.sublabel && (
                  <span className="legend-sublabel">{item.sublabel}</span>
                )}
              </div>
              {item.area !== undefined && (
                <span className="legend-area num">
                  {item.area >= 10 ? `${Math.round(item.area)}` : item.area.toFixed(1)} km²
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
