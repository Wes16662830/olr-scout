import { useState } from "react";
import { Link } from "react-router-dom";
import { DEMO } from "../lib/api";
import { pct, when, zar } from "../lib/format";
import { useData } from "../lib/useData";

type Summary = {
  lots: number; closed: number; still_live: number; sold: number; unsold: number; turnover: number; buyers: number;
  average: number | null; median: number | null; top: number | null; first_close: string | null; last_close: string | null;
};
type AuctionRow = Summary & { source: string; auction_id: string; auction_name: string | null; olr_tag: string | null };
type LotRow = {
  id: number; lot_no: number | null; ring: string | null; title: string; bird_name: string | null; breeder: string | null;
  seller: string | null; sex: string | null; tier: string | null; score: number | null; is_ace: boolean; long_score: number | null;
  final_price: number | null; sale_status: string | null; sale_note: string | null; winner: string | null; bids: number | null;
  closed_at: string | null; url: string; final_read: boolean; yours: "won" | "bid" | null;
};
type Detail = {
  source: string; auction_id: string; auction_name: string | null; summary: Summary;
  price_vs_form: { verified_sold: number; spearman: number | null };
  best_value: LotRow[]; top_sales: LotRow[]; lots: LotRow[]; yours: { won: number; bid: number };
};

const SITE: Record<string, string> = { toppigeon: "Top Pigeon", elite: "Elite", bestpigeon: "Best Pigeon", afripigeon: "AfriPigeon", pah: "PAH" };

function Totals({ s }: { s: Summary }) {
  return (
    <div className="totals">
      <div><b>{s.sold}</b><span>sold of {s.closed}{s.still_live ? ` (+${s.still_live} still live)` : ""}</span></div>
      <div><b>{zar(s.turnover)}</b><span>turnover</span></div>
      <div><b>{s.buyers}</b><span>buyers</span></div>
      <div><b>{zar(s.average)}</b><span>average · median {zar(s.median)}</span></div>
      <div><b>{zar(s.top)}</b><span>top price</span></div>
    </div>
  );
}

function rhoText(r: number | null, n: number): string {
  if (r === null) return `Not enough verified birds sold yet (${n}) to compare price with form.`;
  const a = Math.abs(r);
  const strength = a < 0.4 ? "weakly" : a < 0.6 ? "moderately" : "strongly";
  const stat = `(Spearman ${r.toFixed(2)} over ${n} verified birds sold)`;
  if (a < 0.2) return `Price barely tracked race form here ${stat}: buyers paid for other things than OLR form, so form was cheap.`;
  if (r > 0) return `Price ${strength} followed race form here ${stat}: the better-scoring birds made more money.`;
  return `Price went ${strength} AGAINST race form here ${stat}: the better-scoring birds sold for less — form was cheap.`;
}

function AuctionDetail({ a, onBack }: { a: AuctionRow; onBack: () => void }) {
  const { data, error } = useData<Detail>(`/results/auction?source=${encodeURIComponent(a.source)}&auction_id=${encodeURIComponent(a.auction_id)}`);
  const [show, setShow] = useState<"all" | "sold" | "unsold" | "yours">("all");
  const [sort, setSort] = useState<"lot" | "price" | "score">("lot");
  if (error) return <div className="error">{error}</div>;
  if (!data) return <p>Loading…</p>;
  let rows = data.lots.filter((r) =>
    show === "all" ? true : show === "yours" ? r.yours !== null : r.sale_status === show);
  rows = [...rows].sort((x, y) =>
    sort === "price" ? (y.final_price ?? -1) - (x.final_price ?? -1)
      : sort === "score" ? (y.score ?? -1) - (x.score ?? -1)
        : (x.lot_no ?? 1e9) - (y.lot_no ?? 1e9));
  const q = `source=${encodeURIComponent(a.source)}&auction_id=${encodeURIComponent(a.auction_id)}`;
  return (
    <section>
      <button className="btn ghost small" onClick={onBack}>← All auctions</button>
      <h1>{data.auction_name}</h1>
      <p className="muted">{SITE[data.source] || data.source} · closed {when(data.summary.first_close)} – {when(data.summary.last_close)}</p>
      <Totals s={data.summary} />
      {(data.yours.won > 0 || data.yours.bid > 0) && (
        <p className="banner">You won <b>{data.yours.won}</b> lot(s) and bid on <b>{data.yours.bid}</b> more in this auction.</p>
      )}
      <div className="panel">
        <h2>Price vs form</h2>
        <p>{rhoText(data.price_vs_form.spearman, data.price_vs_form.verified_sold)}</p>
        {data.best_value.length > 0 && (
          <>
            <h3>Best value (highest verified score per rand)</h3>
            <ul>{data.best_value.map((r) => (
              <li key={r.id}>Lot {r.lot_no} · {r.ring} · score {r.score?.toFixed(0)}{r.is_ace ? " · ACE" : ""} · sold for <b>{zar(r.final_price)}</b></li>
            ))}</ul>
          </>
        )}
        {data.top_sales.length > 0 && (
          <>
            <h3>Top sales</h3>
            <ul>{data.top_sales.map((r) => (
              <li key={r.id}>Lot {r.lot_no} · {r.ring} · <b>{zar(r.final_price)}</b> · {r.tier ? `Tier ${r.tier}, score ${r.score?.toFixed(0) ?? "–"}` : "unscored"} · {r.winner ?? "buyer not shown"}</li>
            ))}</ul>
          </>
        )}
      </div>
      <div className="row wrap">
        {(["all", "sold", "unsold", "yours"] as const).map((k) => (
          <button key={k} className={show === k ? "chip on" : "chip"} onClick={() => setShow(k)}>
            {k === "yours" ? "my bids" : k}
          </button>
        ))}
        <span className="muted small">Sort:</span>
        {(["lot", "price", "score"] as const).map((k) => (
          <button key={k} className={sort === k ? "chip on" : "chip"} onClick={() => setSort(k)}>{k}</button>
        ))}
        {!DEMO && <a className="btn ghost small" href={`/api/results/auction.csv?${q}`}>Download CSV</a>}
      </div>
      <div className="scroll"><table className="results-table">
        <thead><tr><th>Lot</th><th>Ring / bird</th><th>Tier · score</th><th>Final price</th><th>Result</th><th>Buyer (as the site shows it)</th><th>Bids</th><th></th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id} className={r.yours ? `mine-${r.yours}` : ""}>
            <td><b>{r.lot_no ?? "–"}</b></td>
            <td><Link to={`/lot/${r.id}`}>{r.ring || r.title.slice(0, 40)}</Link>{r.bird_name ? ` “${r.bird_name}”` : ""}
              {r.breeder && <div className="small muted">{r.breeder}</div>}</td>
            <td>{r.tier ? <span className={`badge tier-${r.tier}`}>{r.tier}</span> : "–"} {r.score?.toFixed(0) ?? ""}
              {r.is_ace ? " ACE" : ""}{r.long_score !== null && r.long_score !== undefined ? <div className="small muted">long {pct(r.long_score)}</div> : null}</td>
            <td><b>{zar(r.final_price)}</b></td>
            <td>{r.sale_status === "sold" ? "sold" : r.sale_status === "unsold" ? <span className="muted">not sold</span> : "–"}
              {r.sale_note && <div className="small muted">{r.sale_note}</div>}
              {!r.final_read && <div className="small muted">final check pending</div>}</td>
            <td>{r.sale_status === "sold"
              ? (r.winner ?? "not shown")
              : r.winner ? <span className="muted">{r.winner}<div className="small">highest bid, not sold</div></span> : "–"}
              {r.yours === "won" && <span className="badge lead"> you</span>}{r.yours === "bid" && <span className="badge"> you bid</span>}</td>
            <td>{r.bids ?? "–"}</td>
            <td><a href={r.url} target="_blank" rel="noopener noreferrer">↗</a></td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

export default function Results() {
  const { data, error } = useData<AuctionRow[]>("/results/auctions", 60_000);
  const [open, setOpen] = useState<AuctionRow | null>(null);
  if (open) return <AuctionDetail a={open} onBack={() => setOpen(null)} />;
  return (
    <section>
      <h1>Auction results</h1>
      <p className="muted">
        Filled in automatically as lots close: final price, sold or not (reserve not met / no bids), and the buyer as the
        site shows it. Each lot page is read once more just after it closes to confirm. Auctions that ended before
        OLR Scout was running cannot be filled in.
      </p>
      {error && <div className="error">{error}</div>}
      {data && data.length === 0 && <p>No auction has closed since OLR Scout started watching. Results appear here as lots close.</p>}
      <div className="grid">
        {data?.map((a) => (
          <button key={`${a.source}:${a.auction_id}`} className="card result-card" onClick={() => setOpen(a)}>
            <div className="lot-head"><span className="lot-auction">{SITE[a.source] || a.source}{a.olr_tag ? ` · ${a.olr_tag}` : ""}</span></div>
            <div className="title">{a.auction_name}</div>
            <Totals s={a} />
            <div className="small muted">Closed {when(a.first_close)}{a.last_close !== a.first_close ? ` – ${when(a.last_close)}` : ""}</div>
          </button>
        ))}
      </div>
    </section>
  );
}
