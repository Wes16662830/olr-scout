export class AuthError extends Error {}

/** Built with VITE_DEMO=1 (the GitHub Pages build): no backend, synthetic snapshot. */
export const DEMO = import.meta.env.VITE_DEMO === "1";
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (DEMO) return (await import("../demo/mock")).demoRequest<T>(method, path, body);
  const r = await fetch(`${API_BASE}/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) throw new AuthError("login required");
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = j.detail || j.message || msg;
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  get: <T>(p: string) => req<T>("GET", p),
  post: <T>(p: string, b: unknown = {}) => req<T>("POST", p, b),
  put: <T>(p: string, b: unknown) => req<T>("PUT", p, b),
  del: <T>(p: string) => req<T>("DELETE", p),
};

export type Tag = { name: string; weight: string };

export interface LotCard {
  id: number;
  source: string;
  auction_name: string | null;
  seller: string | null;
  lot_no: number | null;
  title: string;
  ring: string | null;
  sex: string | null;
  year: number | null;
  bloodline: string | null;
  current_bid: number | null;
  starting_bid: number | null;
  reserve_price: number | null;
  reserve_met: boolean | null;
  bid_count: number | null;
  price: number | null;
  max: number;
  near_max: boolean;
  over_max: boolean;
  ends_at: string | null;
  url: string;
  image_url: string | null;
  status: string;
  olr_tag: string | null;
  tier: "A" | "B" | "C" | "D" | null;
  score: number | null;
  rank_score: number | null;
  tier_label: string | null;
  match_confidence: string;
  match_note: string | null;
  ring_low_confidence: boolean;
  family_tags: Tag[];
  claim_mismatch: boolean;
  own_lot: boolean;
  you_lead: boolean;
  ancestors: { verified: number; mismatch: number; claimed: number } | null;
  seller_stat: { sold_raced: number; aces: number; ace_rate: number; factor: number } | null;
  performance: Record<string, unknown> | null;
  performance_claims: string | null;
  value_rank?: number | null;
}
