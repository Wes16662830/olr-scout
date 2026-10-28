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

export default function AuctionFilter({ lots, selected, onChange }: {
  lots: HasAuction[];
  selected: string[];
  onChange: (keys: string[]) => void;
}) {
  const groups = new Map<string, { name: string; source: string; count: number }>();
  for (const l of lots) {
    const k = auctionKey(l);
    const g = groups.get(k) || { name: l.auction_name || "Unnamed auction", source: l.source, count: 0 };
    g.count += 1;
    groups.set(k, g);
  }
  // Drop selections for auctions that are no longer running.
  const live = selected.filter((k) => groups.has(k));
  if (groups.size === 0) return null;
  const toggle = (k: string) => onChange(live.includes(k) ? live.filter((x) => x !== k) : [...live, k]);
  const sorted = [...groups.entries()].sort((a, b) => b[1].count - a[1].count);
  return (
    <div className="chips auction-filter" role="group" aria-label="Filter by auction">
      <button className={live.length === 0 ? "chip on" : "chip"} onClick={() => onChange([])}>
        All auctions <small>{lots.length}</small>
      </button>
      {sorted.map(([k, g]) => (
        <button key={k} className={live.includes(k) ? "chip on" : "chip"} onClick={() => toggle(k)} title={SOURCE_NAMES[g.source] || g.source}>
          {g.name} <small>{SOURCE_NAMES[g.source] || g.source} · {g.count}</small>
        </button>
      ))}
    </div>
  );
}
