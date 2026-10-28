import { useEffect, useState } from "react";

type HasAuction = { source: string; auction_id?: string; auction_name: string | null };

const KEY = "olr-auction-filter";

export const auctionKey = (l: HasAuction) => `${l.source}:${l.auction_id ?? l.auction_name ?? ""}`;

function read(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

/** Selected auction keys, shared by Suggestions, Closing soon and Export. Empty = all auctions. */
export function useAuctionFilter() {
  const [selected, setSelected] = useState<string[]>(read);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(selected));
    } catch {
      /* private mode: selection lasts for this page only */
    }
  }, [selected]);
  const matches = (l: HasAuction) => selected.length === 0 || selected.includes(auctionKey(l));
  return { selected, setSelected, matches };
}

const SOURCE_NAMES: Record<string, string> = {
  toppigeon: "Top Pigeon", elite: "Elite", bestpigeon: "Best Pigeon", afripigeon: "AfriPigeon", pah: "PAH",
};

export type AuctionOverview = {
  key: string; source: string; auction_id: string; auction_name: string | null; olr_tag: string | null;
  lots: number; suggested: number; tiers: Record<string, number>; hidden: Record<string, number>;
};

/** Why the selected auctions show few or no suggestions. */
export function HiddenExplainer({ overview, selected }: { overview: AuctionOverview[]; selected: string[] }) {
  const chosen = overview.filter((a) => selected.includes(a.key));
  const withHidden = chosen.filter((a) => Object.keys(a.hidden).length > 0);
  if (!withHidden.length) return null;
  return (
    <div className="banner">
      {withHidden.map((a) => (
        <div key={a.key}>
          <b>{a.auction_name}</b>: {a.lots} lots, {a.suggested} suggested. Hidden:{" "}
          {Object.entries(a.hidden).map(([why, n]) => `${n} × ${why}`).join("; ")}.
          {a.hidden && Object.keys(a.hidden).some((k) => k.includes("Tier D")) && (
            <span> These lots become scoreable once this OLR's results are downloaded
              {a.olr_tag ? ` (${a.olr_tag})` : ""} — check the Benzing row on <i>Sources</i>.</span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function AuctionFilter({ lots, selected, onChange, overview }: {
  lots: HasAuction[];
  selected: string[];
  onChange: (keys: string[]) => void;
  /** All running auctions (from the server), so ones with 0 suggestions still show. */
  overview?: AuctionOverview[];
}) {
  const groups = new Map<string, { name: string; source: string; count: number; total?: number }>();
  if (overview) {
    for (const a of overview) {
      groups.set(a.key, { name: a.auction_name || "Unnamed auction", source: a.source, count: a.suggested, total: a.lots });
    }
  } else {
    for (const l of lots) {
      const k = auctionKey(l);
      const g = groups.get(k) || { name: l.auction_name || "Unnamed auction", source: l.source, count: 0 };
      g.count += 1;
      groups.set(k, g);
    }
  }
  // Drop selections for auctions that are no longer running.
  const live = selected.filter((k) => groups.has(k));
  if (groups.size === 0) return null;
  const toggle = (k: string) => onChange(live.includes(k) ? live.filter((x) => x !== k) : [...live, k]);
  const sorted = [...groups.entries()].sort((a, b) => b[1].count - a[1].count || (b[1].total ?? 0) - (a[1].total ?? 0));
  return (
    <div className="chips auction-filter" role="group" aria-label="Filter by auction">
      <button className={live.length === 0 ? "chip on" : "chip"} onClick={() => onChange([])}>
        All auctions <small>{lots.length}</small>
      </button>
      {sorted.map(([k, g]) => (
        <button key={k} className={live.includes(k) ? "chip on" : "chip"} onClick={() => toggle(k)} title={SOURCE_NAMES[g.source] || g.source}>
          {g.name} <small>{SOURCE_NAMES[g.source] || g.source} · {g.total !== undefined ? `${g.count} of ${g.total}` : g.count}</small>
        </button>
      ))}
    </div>
  );
}
