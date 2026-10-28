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
  auction_id: string;
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
  bird_name?: string | null;
  breeding_score?: number | null;
  breeding?: Breeding | null;
  last_bid?: { amount: number; bidder: string | null; at: string | null; count: number | null; bidder_shown: boolean } | null;
  bird?: BirdSummary | null;
  lineage?: Lineage;
}

export interface RaceChip { label: string; name: string; km: number | null; position: number | null; arrived: number | null; pct: number | null; long: boolean; final: boolean }
export interface BirdSummary {
  ring: string; name: string | null; colour: string | null; sex: string | null;
  breeder: string | null; breeder_country: string | null; olr: string; season: number; registered: number | null;
  races: RaceChip[]; arrived_in: number; race_count: number;
  best: { label: string; position: number; arrived: number | null } | null;
  is_ace: boolean; long_score: number | null; final_position: number | null;
  hard_score: number | null; arrival_rate: number | null; lost_after: string | null;
  speed_index: number | null; speed_pct: number | null;
}
export interface OffspringRec { n: number; aces: number; ace_rate: number; mean_long: number;
  birds: { ring: string; name: string | null; olr: string; season: number; long_score: number | null; is_ace: boolean }[] }
export interface Breeding {
  score: number | null; confidence: "none" | "low" | "medium" | "high";
  components?: Record<string, number>; used?: Record<string, number>; missing?: string[];
  progeny?: OffspringRec | null; siblings?: OffspringRec | null; parents_verified?: number; parents_named?: number;
}
export interface ParentRecord { ring: string; name: string | null; olr: string; season: number; long_score: number | null; is_ace: boolean; breeder: string | null }
export interface Lineage {
  parents: { relation: string; ring: string | null; name: string | null; status: string; claims_ace: boolean; record: ParentRecord | null }[];
  grandparents: { total: number; verified: number };
  pedigree_url: string | null;
}
