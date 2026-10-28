import AuctionFilter, { useAuctionFilter } from "../components/AuctionFilter";
import LotCard from "../components/LotCard";
import { LotCard as Lot } from "../lib/api";
import { when } from "../lib/format";
import { useData } from "../lib/useData";

export default function Closing() {
  const { data, error } = useData<{ ends_at: string; lots: Lot[] }[]>("/closing?hours=24", 20_000);
  const filter = useAuctionFilter();
  const all = data?.flatMap((g) => g.lots) ?? [];
  const groups = (data ?? []).map((g) => ({ ...g, lots: g.lots.filter(filter.matches) })).filter((g) => g.lots.length);
  return (
    <section>
      <h1>Closing in the next 24 h</h1>
      <p className="muted">Prices refresh every 20 s on this screen. Close times are read from each lot page and can be extended by late bids.</p>
      {error && <div className="error">{error}</div>}
      {data && <AuctionFilter lots={all} selected={filter.selected} onChange={filter.setSelected} />}
      {data?.length === 0 && <p>Nothing closes in the next 24 hours.</p>}
      {data && data.length > 0 && groups.length === 0 && <p>Nothing in the selected auctions closes in the next 24 hours.</p>}
      {groups.map((g) => (
        <div key={g.ends_at}>
          <h2 className="group">{when(g.ends_at)}</h2>
          <div className="grid">{g.lots.map((l) => <LotCard key={l.id} lot={l} />)}</div>
        </div>
      ))}
    </section>
  );
}
