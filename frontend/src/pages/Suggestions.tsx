import { Link } from "react-router-dom";
import AuctionFilter, { AuctionOverview, HiddenExplainer, useAuctionFilter } from "../components/AuctionFilter";
import LotCard from "../components/LotCard";
import { LotCard as Lot } from "../lib/api";
import { zar } from "../lib/format";
import { useData } from "../lib/useData";

type Diagnosis = { result_birds: number; seasons_ingested: number; results_status: string; results_message: string;
  tiers: Record<string, number>; lots_with_ring: number; sample_lot_rings: string[]; sample_result_rings: string[];
  lots_in_results?: number; result_seasons?: string[] };
type Resp = { items: Lot[]; banners: { source: string; status: string; message: string }[]; max_bid: number; diagnosis?: Diagnosis;
  auctions?: AuctionOverview[] };

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
  if (d.lots_in_results) {
    return (
      <div className="banner">
        <b>{d.lots_in_results} live lots have a ring that is in the OLR results</b> — they are being matched and scored
        now. Refresh this page in a minute. Seasons loaded: {d.result_seasons?.join(", ")}.
      </div>
    );
  }
  return (
    <div className="banner">
      <b>{d.result_birds.toLocaleString("en-ZA")} result birds are loaded ({d.result_seasons?.join(", ") || `${d.seasons_ingested} seasons`}),
      and none of the {d.lots_with_ring} live lot rings is among them yet.</b> Older seasons may still be downloading
      (a ZA 23 bird raced in 2024). If this stays after all seasons are in, the formats differ.
      Lot rings look like: <code>{d.sample_lot_rings.join(" · ") || "none"}</code>. Result rings look like:{" "}
      <code>{d.sample_result_rings.join(" · ")}</code>. Send a screenshot of this box.
    </div>
  );
}

export default function Suggestions() {
  const { data, error, loading } = useData<Resp>("/suggestions", 60_000);
  const filter = useAuctionFilter();
  const shown = data?.items.filter(filter.matches) ?? [];
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
      {data && <AuctionFilter lots={data.items} selected={filter.selected} onChange={filter.setSelected} overview={data.auctions} />}
      {data?.auctions && <HiddenExplainer overview={data.auctions} selected={filter.selected} />}
      {data && data.items.length === 0 && <p>No lots match right now. Check Sources if this looks wrong.</p>}
      {data && data.items.length > 0 && shown.length === 0 && <p>No suggestions in the selected auctions — the yellow box says why.</p>}
      <div className="grid">{shown.map((l) => <LotCard key={l.id} lot={l} />)}</div>
    </section>
  );
}
