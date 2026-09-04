"use client";

import React, { useState } from "react";
import { Manifest } from "@/lib/types";
import { getArtifactUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface ExportBarProps {
  runId: string;
  manifest?: Manifest;
  className?: string;
}

export const ExportBar: React.FC<ExportBarProps> = ({
  runId,
  manifest,
  className,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopyManifest = () => {
    if (!manifest) return;
    navigator.clipboard.writeText(JSON.stringify(manifest, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const hasExportErrors = manifest?.files.some((f) =>
    f.path.includes("EXPORT_ERRORS")
  );

  return (
    <div className={cn("export-bar-container", className)}>
      <div className="export-bar-header">
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-xs)" }}>
          <span className="stat-label">EXPORT PIPELINE</span>
          <span className="export-file-count num">
            {manifest ? `${manifest.file_count} artifacts (${(manifest.total_bytes / (1024 * 1024)).toFixed(1)} MB)` : "Standard Bundle"}
          </span>
        </div>

        {hasExportErrors && (
          <span className="export-error-warning">
            ⚠ One or more export stages encountered non-fatal warnings.
          </span>
        )}
      </div>

      <div className="export-buttons-grid">
        {/* GeoTIFF Rasters */}
        <div className="export-group">
          <span className="export-group-label">GIS Rasters (GeoTIFF)</span>
          <div className="export-btn-row">
            <a
              href={getArtifactUrl(runId, "arrival_time_min.tif")}
              download="arrival_time_min.tif"
              className="export-action-btn"
            >
              Arrival Time .TIF
            </a>
            <a
              href={getArtifactUrl(runId, "max_depth_m.tif")}
              download="max_depth_m.tif"
              className="export-action-btn"
            >
              Peak Depth .TIF
            </a>
            <a
              href={getArtifactUrl(runId, "hazard_class_defra.tif")}
              download="hazard_class_defra.tif"
              className="export-action-btn"
            >
              DEFRA Hazard .TIF
            </a>
          </div>
        </div>

        {/* Vector Bundles */}
        <div className="export-group">
          <span className="export-group-label">Vector Layers (Shapefile & KML)</span>
          <div className="export-btn-row">
            <a
              href={getArtifactUrl(runId, "shapefile/arrival_isochrones.zip")}
              download="arrival_isochrones.zip"
              className="export-action-btn"
            >
              Isochrones .ZIP
            </a>
            <a
              href={getArtifactUrl(runId, "shapefile/settlements_at_risk.zip")}
              download="settlements_at_risk.zip"
              className="export-action-btn"
            >
              Settlements .ZIP
            </a>
            <a
              href={getArtifactUrl(runId, "kml/inundation_extent.kml")}
              download="inundation_extent.kml"
              className="export-action-btn"
            >
              Google Earth .KML
            </a>
          </div>
        </div>

        {/* Audit & Report */}
        <div className="export-group">
          <span className="export-group-label">Documentation & Audit</span>
          <div className="export-btn-row">
            <a
              href={`/runs/${runId}/report`}
              target="_blank"
              rel="noopener noreferrer"
              className="export-action-btn export-btn-highlight"
            >
              Official PDF Report
            </a>
            <a
              href={getArtifactUrl(runId, "metadata.json")}
              download="metadata.json"
              className="export-action-btn"
            >
              metadata.json
            </a>
            <button
              type="button"
              onClick={handleCopyManifest}
              className="export-action-btn"
            >
              {copied ? "✓ Copied Manifest" : "Copy MANIFEST.json"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
