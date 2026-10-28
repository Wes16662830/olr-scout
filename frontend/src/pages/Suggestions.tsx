import { Link } from "react-router-dom";
import LotCard from "../components/LotCard";
import { LotCard as Lot } from "../lib/api";
import { zar } from "../lib/format";
import { useData } from "../lib/useData";

type Diagnosis = { result_birds: number; seasons_ingested: number; results_status: string; results_message: string;
  tiers: Record<string, number>; lots_with_ring: number; sample_lot_rings: string[]; sample_result_rings: string[] };
type Resp = { items: Lot[]; banners: { source: string; status: string; message: string }[]; max_bid: number; diagnosis?: Diagnosis };

function WhyNoScores({ d }: { d: Diagnosis }) {
  const verified = (d.tiers.A || 0) + (d.tiers.B || 0);
  if (verified > 0) return null;
  if (d.result_birds === 0) {
    return (
      <div className="banner">
        <b>No OLR race results are loaded yet</b>, so no lot can be verified and every lot is Tier C (seller-claimed,
        same score). Results source status: <b>{d.results_status}</b>{d.results_message ? ` — ${d.results_message}` : ""}.
        Go to <Link to="/sources">Sources</Link> → <i>Ingest OLR results now</i> and wait for the Benzing row to show a
        bird count. If it shows <i>error</i>, send a screenshot of that row with “detail” opened.
      </div>
    );
  }
  return (
    <div className="banner">
      <b>{d.result_birds.toLocaleString("en-ZA")} result birds are loaded ({d.seasons_ingested} seasons), but no live lot
      matched them.</b> Usually the ring formats differ between the sites. {d.lots_with_ring} live lots have a ring.
      Lot rings look like: <code>{d.sample_lot_rings.join(" · ") || "none"}</code>. Result rings look like:{" "}
      <code>{d.sample_result_rings.join(" · ")}</code>. Send a screenshot of this box.
    </div>
  );
}

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
      {data?.diagnosis && <WhyNoScores d={data.diagnosis} />}
      {error && <div className="error">{error}</div>}
      {loading && !data && <p>Loading…</p>}
      {data && data.items.length === 0 && <p>No lots match right now. Check Sources if this looks wrong.</p>}
      <div className="grid">{data?.items.map((l) => <LotCard key={l.id} lot={l} />)}</div>
    </section>
  );
}
