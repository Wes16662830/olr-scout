// DEMO MODE: serves the API from a snapshot of SYNTHETIC data (see
// backend/scripts/build_demo_snapshot.py) so the static GitHub Pages build
// works without the Python backend. Nothing here is real auction data.
import snapshot from "./snapshot.json";

type Snap = {
  generated_at: string;
  get: Record<string, unknown>;
  plans: Record<string, unknown>;
  xlsx_base64: string;
  default_goal: Record<string, unknown>;
};
const snap = snapshot as unknown as Snap;

export const NOT_IN_DEMO = "Not available in the demo — this needs the OLR Scout backend running.";

// Close times in the snapshot are shifted so countdowns stay in the future.
const offsetMs = Date.now() - new Date(snap.generated_at).getTime();

function shift<T>(v: T): T {
  if (Array.isArray(v)) return v.map(shift) as T;
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
      out[k] = (k === "ends_at") && typeof x === "string" ? new Date(new Date(x).getTime() + offsetMs).toISOString() : shift(x);
    }
    return out as T;
  }
  return v;
}

const store = {
  read<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem("olr-demo-" + key);
      return raw ? (JSON.parse(raw) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  write(key: string, value: unknown) {
    try {
      localStorage.setItem("olr-demo-" + key, JSON.stringify(value));
    } catch {
      /* private mode: fine, state lasts for the page only */
    }
  },
};

type LotCard = { id: number; [k: string]: unknown };
const allLots = () => shift(snap.get["/lots?status=all"] as LotCard[]);
const watched = () => store.read<number[]>("watch", ((snap.get["/watchlist"] as { lot: LotCard }[]) || []).map((w) => w.lot.id));

function get(path: string): unknown {
  const [base, query = ""] = path.split("?");
  const q = new URLSearchParams(query);
  if (base === "/watchlist") {
    const lots = allLots();
    return watched().flatMap((id, i) => {
      const lot = lots.find((l) => l.id === id);
      return lot ? [{ watch: { id: i + 1, near_max_within: null, closes_in: [30, 10], above_max: true }, lot }] : [];
    });
  }
  if (base === "/alerts") {
    const read = store.read<boolean>("alerts-read", false);
    const alerts = (snap.get["/alerts"] as { read: boolean }[]).map((a) => ({ ...a, read: read || a.read }));
    return q.get("unread") ? alerts.filter((a) => !a.read) : alerts;
  }
  if (base === "/families") {
    const min = Number(q.get("min_entries") || 1);
    const olr = q.get("olr");
    const data = snap.get["/families?min_entries=1&limit=300"] as { families: { entries: number; seasons: { olr: string }[] }[] };
    return { ...data, families: data.families.filter((f) => f.entries >= min && (!olr || f.seasons.some((s) => s.olr === olr))) };
  }
  if (base === "/search") {
    // Same rules as the backend, on the snapshot's cards (no pedigree-ring search here).
    const raw = (q.get("q") || "").trim();
    const m = raw.match(/^(?:lot\s*(?:no\.?|nr\.?|#)?\s*)?#?(\d{1,4})$/i);
    const norm = raw.toUpperCase().replace(/[^A-Z0-9]/g, "");
    const words = !m && raw.length >= 3 && /[a-z]/i.test(raw) ? raw.toLowerCase() : null;
    return allLots().flatMap((l) => {
      const why: string[] = [];
      const ring = String(l.ring || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
      if (m && l.lot_no === Number(m[1])) why.push("lot number");
      if (norm.replace(/\D/g, "").length >= 3 && ring.includes(norm)) why.push("bird's ring");
      if (words && String(l.seller || "").toLowerCase().includes(words)) why.push("seller / breeder");
      if (words && !why.length && `${l.title} ${l.bloodline || ""}`.toLowerCase().includes(words)) why.push("mentioned in the listing");
      return why.length ? [{ ...l, found_by: why }] : [];
    });
  }
  if (base === "/settings") return store.read("settings", snap.get["/settings"]);
  if (base === "/inventory") return store.read("inventory", snap.get["/inventory"]);
  if (base === "/closing") return shift(snap.get["/closing?hours=24"]);
  if (base === "/lots" && !q.get("status")) return allLots().filter((l) => l.status === "live");
  if (base.startsWith("/lots/")) {
    const d = snap.get[base];
    if (!d) throw new Error("lot not in the demo snapshot");
    return { ...(shift(d) as object), watched: watched().includes(Number(base.split("/")[2])) };
  }
  const exact = snap.get[path] ?? snap.get[base];
  if (exact === undefined) throw new Error(NOT_IN_DEMO);
  return shift(exact);
}

export async function demoRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  await new Promise((r) => setTimeout(r, 120)); // feel like a network call
  const b = (body || {}) as Record<string, unknown>;
  if (method === "GET") return get(path) as T;
  if (path === "/login" || path === "/logout") return { ok: true } as T;
  const watchMatch = path.match(/^\/lots\/(\d+)\/watch$/);
  if (watchMatch) {
    const id = Number(watchMatch[1]);
    const w = watched().filter((x) => x !== id);
    store.write("watch", method === "DELETE" ? w : [...w, id]);
    return { ok: true } as T;
  }
  if (path === "/alerts/read") {
    store.write("alerts-read", true);
    return { ok: true } as T;
  }
  if (path === "/settings" && method === "PUT") {
    store.write("settings", body);
    return body as T;
  }
  if (path === "/inventory" && method === "POST") {
    const inv = store.read<Record<string, unknown>[]>("inventory", []);
    const item = { id: Date.now(), ...b };
    store.write("inventory", [...inv, item]);
    return item as T;
  }
  const invMatch = path.match(/^\/inventory\/(\d+)$/);
  if (invMatch && method === "DELETE") {
    store.write("inventory", store.read<{ id: number }[]>("inventory", []).filter((x) => x.id !== Number(invMatch[1])));
    return { ok: true } as T;
  }
  if (path === "/builder/plan") {
    const fams = (b.core_families as string[]) || [];
    const plan = (snap.plans[fams[0] || ""] || snap.plans[""]) as { notes: string[] };
    const g = snap.default_goal;
    return {
      ...(shift(plan) as object),
      notes: [
        `DEMO: plan precomputed for ${g.pairs} pairs and a R${Number(g.budget).toLocaleString("en-ZA").replace(/\s/g, ",")} budget` +
          (fams.length > 1 ? `, first family only (${fams[0]})` : "") + ". Your goal settings are not applied without the backend.",
        ...plan.notes,
      ],
    } as T;
  }
  throw new Error(NOT_IN_DEMO);
}

export const demoExports = {
  csv: () => URL.createObjectURL(new Blob([snap.get["/export.csv"] as string], { type: "text/csv" })),
  xlsx: () => {
    const bytes = Uint8Array.from(atob(snap.xlsx_base64), (c) => c.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
  },
};
