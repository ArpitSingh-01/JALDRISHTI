"use client";

import React, { useState } from "react";
import { Legend, LegendType } from "@/components/shared/Legend";
import { SettlementProperties } from "@/lib/types";
import { formatArrival, formatDepth, cn } from "@/lib/utils";
import type { FeatureCollection } from "geojson";

export interface MapCanvasProps {
  layer: LegendType;
  currentMinute: number;
  isochrones?: FeatureCollection;
  settlements?: FeatureCollection;
  selectedSettlement?: string | null;
  onSelectSettlement?: (name: string) => void;
  className?: string;
}

export const MapCanvas: React.FC<MapCanvasProps> = ({
  layer,
  currentMinute,
  isochrones,
  settlements,
  selectedSettlement,
  onSelectSettlement,
  className,
}) => {
  const [hoveredFeature, setHoveredFeature] = useState<SettlementProperties | null>(null);

  // Settlement features
  const settlementFeatures = settlements?.features || [];

  return (
    <div id="map-viewport" className={cn("map-canvas-container", className)}>
      {/* Visual Simulation Canvas */}
      <div className="map-viewport-surface">
        {/* Synthetic Vector / Isochrone Display for Demo & Offline */}
        <svg
          className="map-svg-renderer"
          viewBox="0 0 800 600"
          preserveAspectRatio="xMidYMid meet"
          aria-label="Simulation Map Viewport"
        >
          <defs>
            {/* Terrain grid pattern */}
            <pattern id="grid-pattern" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="var(--map-graticule)" strokeWidth="0.5" />
            </pattern>

            {/* Hillshade shadow simulation */}
            <radialGradient id="valley-shade" cx="45%" cy="30%" r="60%">
              <stop offset="0%" stopColor="transparent" />
              <stop offset="100%" stopColor="var(--map-land-shade)" stopOpacity="0.4" />
            </radialGradient>
          </defs>

          {/* Background land surface (§9.2: mid-grey, preserved lightness) */}
          <rect width="800" height="600" fill="var(--map-land)" />
          <rect width="800" height="600" fill="url(#valley-shade)" />
          <rect width="800" height="600" fill="url(#grid-pattern)" />

          {/* River / Valley Channel Guide */}
          <path
            d="M 400 60 Q 420 180 370 280 T 320 420 T 260 550"
            fill="none"
            stroke="var(--ramp-pre-existing-water)"
            strokeWidth="8"
            strokeLinecap="round"
            opacity="0.7"
          />

          {/* Isochrone / Hazard Inundation Polygons */}
          {/* Band 4 (>120 min) */}
          <path
            d="M 390 60 Q 440 200 390 320 T 330 460 T 250 560 L 220 540 Q 300 400 350 260 T 370 60 Z"
            fill="var(--ramp-arrival-4)"
            opacity={currentMinute >= 120 ? 0.85 : 0.15}
            className="isochrone-polygon"
          />

          {/* Band 3 (60-120 min) */}
          <path
            d="M 395 60 Q 430 190 380 300 T 325 440 T 255 530 L 240 515 Q 310 390 360 250 T 380 60 Z"
            fill="var(--ramp-arrival-3)"
            opacity={currentMinute >= 60 ? 0.85 : 0.15}
            className="isochrone-polygon"
          />

          {/* Band 2 (30-60 min) */}
          <path
            d="M 398 60 Q 420 180 375 280 T 320 400 L 290 385 Q 335 270 375 170 T 385 60 Z"
            fill="var(--ramp-arrival-2)"
            opacity={currentMinute >= 30 ? 0.9 : 0.15}
            className="isochrone-polygon"
          />

          {/* Band 1 (15-30 min) */}
          <path
            d="M 400 60 Q 418 160 370 260 L 330 245 Q 365 150 390 60 Z"
            fill="var(--ramp-arrival-1)"
            opacity={currentMinute >= 15 ? 0.92 : 0.15}
            className="isochrone-polygon"
          />

          {/* Band 0 (0-15 min) — Dam breach zone */}
          <path
            d="M 400 60 Q 412 110 385 160 L 360 150 Q 380 100 395 60 Z"
            fill="var(--ramp-arrival-0)"
            opacity={currentMinute >= 0 ? 0.95 : 0.2}
            className="isochrone-polygon"
          />

          {/* Dam Structure Marker */}
          <g transform="translate(400, 60)">
            <rect x="-25" y="-6" width="50" height="12" fill="var(--color-navy)" rx="2" />
            <text x="0" y="-12" textAnchor="middle" fill="var(--color-ink)" fontSize="11" fontWeight="bold">
              Tehri Dam Axis (830m FRL)
            </text>
          </g>

          {/* Settlement Nodes */}
          {settlementFeatures.map((feat, idx: number) => {
            const props = feat.properties as SettlementProperties;
            // Coordinate mapping to SVG space
            const xCoords = [385, 370, 315, 255, 480];
            const yCoords = [160, 280, 420, 540, 240];
            const x = xCoords[idx % xCoords.length];
            const y = yCoords[idx % yCoords.length];

            const isWetted = currentMinute >= props.arr_min && props.arr_min !== -1;
            const isSelected = selectedSettlement === props.name;

            return (
              <g
                key={props.name}
                transform={`translate(${x}, ${y})`}
                className="settlement-map-marker"
                onClick={() => onSelectSettlement && onSelectSettlement(props.name)}
                onMouseEnter={() => setHoveredFeature(props)}
                onMouseLeave={() => setHoveredFeature(null)}
                style={{ cursor: "pointer" }}
              >
                {/* Ping animation when wave hits */}
                {isWetted && (
                  <circle r="16" fill="var(--color-accent)" opacity="0.3">
                    <animate attributeName="r" values="8;20;8" dur="2s" repeatCount="indefinite" />
                  </circle>
                )}

                <circle
                  r={isSelected ? "8" : "6"}
                  fill={isWetted ? "var(--color-accent)" : "var(--color-paper)"}
                  stroke="var(--color-navy)"
                  strokeWidth="2"
                />

                <text
                  x="12"
                  y="4"
                  fill="var(--map-label)"
                  fontSize="12"
                  fontWeight={isSelected ? "bold" : "normal"}
                  className="settlement-map-label"
                >
                  {props.name} {props.arr_min !== -1 && `(${props.arr_min}m)`}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Hover Tooltip HUD */}
        {hoveredFeature && (
          <div
            className="map-tooltip-hud"
            style={{
              position: "absolute",
              bottom: "var(--space-md)",
              left: "var(--space-md)",
            }}
          >
            <h4 style={{ fontSize: "var(--text-sm)", color: "var(--color-ink)", fontWeight: "var(--weight-bold)" }}>
              {hoveredFeature.name}
            </h4>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-2)", marginTop: "4px" }}>
              <span>Arrival: <strong>{formatArrival(hoveredFeature.arr_min)}</strong></span>
              <span style={{ marginInline: "var(--space-xs)" }}>•</span>
              <span>Depth: <strong>{formatDepth(hoveredFeature.depth_m)}</strong></span>
              <span style={{ marginInline: "var(--space-xs)" }}>•</span>
              <span>Hazard: <strong>{hoveredFeature.haz_class}</strong></span>
            </div>
          </div>
        )}
      </div>

      {/* Frosted-Glass Map HUD Overlay (§9.1, §2.5 morphism signature) */}
      <div className="map-frosted-hud">
        <Legend type={layer} compact />
      </div>
    </div>
  );
};
