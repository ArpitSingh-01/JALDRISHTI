"use client";

import React from "react";
import { cn } from "@/lib/utils";

export type MapLayerId =
  | "arrival"
  | "depth"
  | "speed"
  | "dv"
  | "defra"
  | "aidr";

export interface LayerSwitcherProps {
  activeLayer: MapLayerId;
  onChangeLayer: (layer: MapLayerId) => void;
  className?: string;
}

const LAYERS = [
  {
    id: "arrival" as MapLayerId,
    label: "Arrival Time",
    band: "arrival_time_min",
    unit: "min",
    desc: "Primary decision layer: time to first wetted front",
    isPrimary: true,
  },
  {
    id: "depth" as MapLayerId,
    label: "Peak Depth",
    band: "max_depth_m",
    unit: "m",
    desc: "Maximum inundation depth across run duration",
  },
  {
    id: "speed" as MapLayerId,
    label: "Peak Velocity",
    band: "max_speed_ms",
    unit: "m/s",
    desc: "Maximum flow speed attained by the flood wave",
  },
  {
    id: "dv" as MapLayerId,
    label: "Peak Depth × Velocity",
    band: "max_depth_velocity",
    unit: "m²/s",
    desc: "Hydrodynamic impulse / structural hazard rating",
  },
  {
    id: "defra" as MapLayerId,
    label: "DEFRA Hazard (UK)",
    band: "hazard_class_defra",
    unit: "class 0-3",
    desc: "HR = d(v + 0.5) + DF (Low to Extreme)",
  },
  {
    id: "aidr" as MapLayerId,
    label: "AIDR Hazard (H1–H6)",
    band: "hazard_class_aidr",
    unit: "class 1-6",
    desc: "Australian combined flood hazard categories",
  },
];

export const LayerSwitcher: React.FC<LayerSwitcherProps> = ({
  activeLayer,
  onChangeLayer,
  className,
}) => {
  return (
    <aside className={cn("layer-switcher-rail", className)} aria-label="Map Layer Selection">
      <div className="layer-switcher-header">
        <span className="stat-label">MAP LAYERS ({LAYERS.length})</span>
      </div>

      <nav className="layer-buttons-list" role="tablist">
        {LAYERS.map((layer) => {
          const isActive = activeLayer === layer.id;
          return (
            <button
              key={layer.id}
              role="tab"
              aria-selected={isActive}
              aria-controls="map-viewport"
              type="button"
              className={cn(
                "layer-button",
                isActive && "layer-button-active",
                layer.isPrimary && "layer-button-primary"
              )}
              onClick={() => onChangeLayer(layer.id)}
            >
              <div className="layer-button-top">
                <span className="layer-button-title">{layer.label}</span>
                {layer.isPrimary && (
                  <span className="layer-primary-tag">DEFAULT</span>
                )}
              </div>
              <span className="layer-button-desc">{layer.desc}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
};
