/**
 * Formatting utilities for JALDRISHTI.
 *
 * Every formatting rule here corresponds to a spec rule in frontend.md §6, §11.
 * These are the functions that prevent silent display bugs — read the comments.
 */

/**
 * Format arrival time: null → "not reached", never "0".
 * Covers §6.3 rule 1 and §6.8 (vector sentinel -1).
 *
 * The backend once had exactly this bug: the reservoir is wet at t=0, so a naive
 * min() gave "0 min after failure." This function exists to prevent that.
 */
export function formatArrival(
  minutes: number | null | undefined,
): string {
  if (minutes === null || minutes === undefined) return "not reached";
  if (minutes === -1) return "not reached"; // vector layer sentinel (§6.8)
  if (minutes <= 0) return "< 1 min";
  return `${Math.round(minutes)} min`;
}

/**
 * Format area: ≥ 10 km² as integer, < 10 as one decimal.
 * Matches the headline() logic in summary.py.
 */
export function formatArea(km2: number): string {
  if (km2 >= 10) return `${Math.round(km2).toLocaleString()} km²`;
  return `${km2.toFixed(1)} km²`;
}

/**
 * Format population: use reported_population (2 sig figs), not total_population.
 * §6.7, §11.3: "Reporting a raw 12,437 implies a per-person census we do not have."
 */
export function formatPopulation(reported: number): string {
  return `about ${reported.toLocaleString()} people`;
}

/**
 * Format depth with one decimal, mono-spaced.
 */
export function formatDepth(m: number): string {
  return `${m.toFixed(1)} m`;
}

/**
 * Format speed with one decimal.
 */
export function formatSpeed(ms: number): string {
  return `${ms.toFixed(1)} m/s`;
}

/**
 * Format a number to 2 significant figures.
 * Used for reported_population computation if needed client-side.
 */
export function toTwoSigFigs(n: number): number {
  if (n === 0) return 0;
  const d = Math.ceil(Math.log10(Math.abs(n)));
  const power = 2 - d;
  const magnitude = Math.pow(10, power);
  return Math.round(n * magnitude) / magnitude;
}

/**
 * Format volume error for provenance display.
 */
export function formatVolumeError(error: number): string {
  if (Math.abs(error) < 1e-12) return "< 1×10⁻¹²";
  return error.toExponential(2);
}

/**
 * Format wall time for human display.
 */
export function formatWallTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins} min ${secs.toFixed(0)} s`;
}

/**
 * Format simulated duration in hours.
 */
export function formatDuration(seconds: number): string {
  const hours = seconds / 3600;
  return `${hours.toFixed(1)} h`;
}

/**
 * Get hazard class CSS variable name for a DEFRA class index.
 */
export function defraRampVar(index: number): string {
  return `var(--ramp-defra-${index})`;
}

/**
 * Get arrival band CSS variable name for a band index.
 */
export function arrivalRampVar(index: number): string {
  return `var(--ramp-arrival-${index})`;
}

/**
 * Determine if a run is presentable as fact.
 * Convenience wrapper for honesty.presentable_as_fact.
 */
export function isPresentable(honesty: {
  presentable_as_fact: boolean;
}): boolean {
  return honesty.presentable_as_fact;
}

/**
 * Clamp a number to a range.
 */
export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/**
 * Join class names, filtering out falsy values.
 */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
