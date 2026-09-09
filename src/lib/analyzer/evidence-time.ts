export function timestampSeconds(timestamp: string): number | null {
  if (!/^(?:\d{1,2}:)?\d{1,3}:\d{2}(?:\.\d{1,3})?$/.test(timestamp)) return null;
  const parts = timestamp.split(":").map(Number);
  if (parts.at(-1)! >= 60 || (parts.length === 3 && parts[1] >= 60)) return null;
  return parts.reduce((total, part) => total * 60 + part, 0);
}
