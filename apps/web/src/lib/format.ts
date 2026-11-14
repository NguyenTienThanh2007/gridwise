/** Formatting shared by every view. Deterministic: no locale or time-zone surprises. */

/** `2026-11-14T15:15:19.123+00:00` → `2026-11-14 15:15 UTC`. */
export function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const iso = date.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

/** The first characters of a hash, enough to tell hashes apart on screen. */
export function shortHash(value: string, length = 12): string {
  return value.length <= length ? value : `${value.slice(0, length)}…`;
}
