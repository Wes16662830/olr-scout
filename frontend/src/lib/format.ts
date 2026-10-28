import { useEffect, useState } from "react";

export const TZ = "Africa/Johannesburg";

export function zar(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return "R" + Math.round(n).toLocaleString("en-ZA").replace(/ |\s/g, ",");
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("en-ZA", {
    timeZone: TZ, weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

export function pct(x: unknown): string {
  return typeof x === "number" ? `${(x * 100).toFixed(1)}%` : "–";
}

export function useNow(ms = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function countdown(iso: string | null, now: number): { text: string; urgent: boolean; over: boolean } {
  if (!iso) return { text: "end time unknown", urgent: false, over: false };
  const s = Math.floor((new Date(iso).getTime() - now) / 1000);
  if (s <= 0) return { text: "closing / closed", urgent: true, over: true };
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const text = d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m ${sec.toString().padStart(2, "0")}s`;
  return { text, urgent: s < 600, over: false };
}
