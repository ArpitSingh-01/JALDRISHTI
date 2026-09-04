"use client";

import React, { useState } from "react";
import { formatArrival, formatDepth, formatSpeed, cn } from "@/lib/utils";
import { SettlementProperties } from "@/lib/types";

export interface SettlementsTableProps {
  settlements: SettlementProperties[];
  onSelectSettlement?: (name: string) => void;
  selectedSettlement?: string | null;
  className?: string;
}

export const SettlementsTable: React.FC<SettlementsTableProps> = ({
  settlements,
  onSelectSettlement,
  selectedSettlement,
  className,
}) => {
  const [sortBy, setSortBy] = useState<"arrival" | "depth" | "name">("arrival");
  const [sortAsc, setSortAsc] = useState(true);

  const handleSort = (field: "arrival" | "depth" | "name") => {
    if (sortBy === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortBy(field);
      setSortAsc(true);
    }
  };

  const sortedSettlements = [...settlements].sort((a, b) => {
    if (sortBy === "arrival") {
      // Put "not reached" (-1) at the bottom
      const aVal = a.arr_min === -1 ? 99999 : a.arr_min;
      const bVal = b.arr_min === -1 ? 99999 : b.arr_min;
      return sortAsc ? aVal - bVal : bVal - aVal;
    }
    if (sortBy === "depth") {
      return sortAsc ? a.depth_m - b.depth_m : b.depth_m - a.depth_m;
    }
    return sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
  });

  return (
    <div className={cn("settlements-panel", className)}>
      <div className="settlements-header">
        <div>
          <span className="stat-label">SETTLEMENT TIMETABLE</span>
          <h3 className="settlements-title">Settlements at Risk</h3>
        </div>
        <span className="settlements-count num">{settlements.length} sites</span>
      </div>

      <div className="settlements-table-container">
        <table>
          <thead>
            <tr>
              <th
                onClick={() => handleSort("name")}
                style={{ cursor: "pointer" }}
                title="Sort by Settlement Name"
              >
                Settlement {sortBy === "name" && (sortAsc ? "▲" : "▼")}
              </th>
              <th
                onClick={() => handleSort("arrival")}
                style={{ cursor: "pointer" }}
                title="Sort by Arrival Time"
              >
                Arrival {sortBy === "arrival" && (sortAsc ? "▲" : "▼")}
              </th>
              <th
                onClick={() => handleSort("depth")}
                style={{ cursor: "pointer" }}
                title="Sort by Peak Depth"
              >
                Peak Depth {sortBy === "depth" && (sortAsc ? "▲" : "▼")}
              </th>
              <th>Hazard Rating</th>
            </tr>
          </thead>
          <tbody>
            {sortedSettlements.map((s) => {
              const isNotReached = s.arr_min === -1 || !s.flooded;
              const isSelected = selectedSettlement === s.name;

              return (
                <tr
                  key={s.name}
                  className={cn(
                    "settlement-row",
                    isNotReached && "settlement-row-safe",
                    isSelected && "settlement-row-selected",
                    onSelectSettlement && "settlement-row-interactive"
                  )}
                  onClick={() => onSelectSettlement && onSelectSettlement(s.name)}
                >
                  <td className="settlement-name-cell">
                    <span className="settlement-name">{s.name}</span>
                    {s.population && (
                      <span className="settlement-pop num">
                        Pop: {s.population.toLocaleString()}
                      </span>
                    )}
                  </td>

                  <td className="settlement-arrival-cell num">
                    {isNotReached ? (
                      <span className="settlement-not-reached">not reached</span>
                    ) : (
                      <span className="settlement-arrival-time">
                        {formatArrival(s.arr_min)}
                      </span>
                    )}
                  </td>

                  <td className="settlement-depth-cell num">
                    {isNotReached ? "—" : formatDepth(s.depth_m)}
                  </td>

                  <td className="settlement-hazard-cell">
                    {isNotReached ? (
                      <span className="hazard-pill hazard-none">None</span>
                    ) : (
                      <span className={cn("hazard-pill", `hazard-${s.haz_class.toLowerCase()}`)}>
                        {s.haz_class}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
