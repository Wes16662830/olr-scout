import LotCard from "../components/LotCard";
import { LotCard as Lot } from "../lib/api";
import { zar } from "../lib/format";
import { useData } from "../lib/useData";

type Resp = { items: Lot[]; banners: { source: string; status: string; message: string }[]; max_bid: number };

export default function Suggestions() {
  const { data, error, loading } = useData<Resp>("/suggestions", 60_000);
  return (
    <section>
      <h1>Suggestions</h1>
      {data?.banners.map((b) => (
        <div key={b.source} className="banner">Source <b>{b.source}</b> is {b.status}: {b.message}</div>
      ))}
      <p className="muted">
        Active lots at or under your max ({zar(data?.max_bid)}), ranked by evidence tier, then score weighted by your
        family preferences. Tier C is seller-claimed and capped at 60. Tier D is never suggested.
      </p>
      {error && <div className="error">{error}</div>}
      {loading && !data && <p>Loading…</p>}
      {data && data.items.length === 0 && <p>No lots match right now. Check Sources if this looks wrong.</p>}
      <div className="grid">{data?.items.map((l) => <LotCard key={l.id} lot={l} />)}</div>
    </section>
  );
}
