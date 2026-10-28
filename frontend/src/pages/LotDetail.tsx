import { useState } from "react";
import { useParams } from "react-router-dom";
import LotCard from "../components/LotCard";
import { api, LotCard as Lot } from "../lib/api";
import { pct, when, zar } from "../lib/format";
import { useData } from "../lib/useData";

type Race = { olr: string; season_year: number; flight: string; distance_km: number | null; position: number | null; arrived: number | null; percentile: number };
type Claim = { id: number; relation: string; ring: string | null; name: string | null; text: string; origin: string; claims_ace: boolean; status: string; bird: { ring: string; long_score: number; is_ace: boolean; olr: string; year: number } | null };
type Detail = Lot & {
  description: string | null; pedigree_text: string | null; pedigree_url: string | null;
  races: Race[]; family: { key: string; team: string; rows: { season_id: number | null; entries: number; aces: number; finalists: number; ace_rate: number }[] } | null;
  family_birds: { ring: string; long_score: number; is_ace: boolean; year: number; olr: string }[];
  price_history: { at: string; current_bid: number | null; bid_count: number | null }[];
  bid_history: { bidder: string | null; amount: number | null; at: string | null }[];
  claims: Claim[]; watched: boolean; score_detail: Record<string, unknown>;
};

export default function LotDetail() {
  const { id } = useParams();
  const { data, error, reload } = useData<Detail>(`/lots/${id}`, 30_000);
  const [ring, setRing] = useState("");
  const [msg, setMsg] = useState("");
  if (error) return <div className="error">{error}</div>;
  if (!data) return <p>Loading…</p>;
  const override = async (body: unknown) => {
    try { await api.post(`/lots/${id}/override`, body); setMsg("Saved."); reload(); } catch (e) { setMsg((e as Error).message); }
  };
  return (
    <section>
      <LotCard lot={data} onWatch={reload} />
      <h2>Match</h2>
      <p>Confidence: <b>{data.match_confidence}</b> {data.match_note && <span className="muted">— {data.match_note}</span>}</p>
      <div className="row wrap">
        <input placeholder="This lot = ring… (e.g. BE-25-6087189)" value={ring} onChange={(e) => setRing(e.target.value)} />
        <button className="btn" onClick={() => override({ ring })}>Set match</button>
        <button className="btn ghost" onClick={() => override({ none: true })}>No results for this bird</button>
        <button className="btn ghost" onClick={() => override({ clear: true })}>Clear override</button>
        <span className="muted">{msg}</span>
      </div>

      {data.races.length > 0 && (
        <>
          <h2>Race by race</h2>
          <div className="scroll"><table>
            <thead><tr><th>OLR</th><th>Season</th><th>Race</th><th>km</th><th>Pos</th><th>Arrived</th><th>Percentile</th></tr></thead>
            <tbody>{data.races.map((r, i) => (
              <tr key={i}><td>{r.olr}</td><td>{r.season_year}</td><td>{r.flight}</td><td>{r.distance_km ?? "–"}</td>
                <td>{r.position ?? "missing"}</td><td>{r.arrived ?? "–"}</td><td>{r.position ? pct(r.percentile) : "100% (missing)"}</td></tr>
            ))}</tbody>
          </table></div>
        </>
      )}
      {data.tier === "A" && data.score_detail?.components != null && (
        <p className="muted">Score parts (0–1): {Object.entries(data.score_detail.components as Record<string, number>).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ")}
          {(data.score_detail.missing as string[])?.length ? ` · no data: ${(data.score_detail.missing as string[]).join(", ")}` : ""}</p>
      )}

      {data.family && (
        <>
          <h2>Family: {data.family.team}</h2>
          <table><thead><tr><th>Season</th><th>Entries</th><th>Aces</th><th>Finalists</th><th>Ace rate (shrunk)</th></tr></thead>
            <tbody>{data.family.rows.map((r, i) => <tr key={i}><td>{r.season_id ?? "all"}</td><td>{r.entries}</td><td>{r.aces}</td><td>{r.finalists}</td><td>{pct(r.ace_rate)}</td></tr>)}</tbody></table>
          <h3>Other birds from this family</h3>
          <ul>{data.family_birds.map((b) => <li key={b.ring + b.year}>{b.ring} · {b.olr} {b.year} · long {pct(b.long_score)}{b.is_ace ? " · ACE" : ""}</li>)}</ul>
        </>
      )}

      <h2>Ancestors</h2>
      {data.claims.length === 0 && <p className="muted">No ancestor rings found in the text. Use Pedigree review to add them or OCR the pedigree.</p>}
      <ul>{data.claims.map((c) => (
        <li key={c.id}><span className={`badge st-${c.status}`}>{c.status}</span> {c.relation}: <b>{c.ring}</b> {c.name && `“${c.name}”`}
          {c.bird ? ` → ${c.bird.olr} ${c.bird.year}, long ${pct(c.bird.long_score)}${c.bird.is_ace ? ", ACE" : ""}` : " → not found in OLR results (claimed only)"}
          <div className="muted small">“{c.text}” ({c.origin})</div></li>
      ))}</ul>

      {data.performance_claims && <><h2>Seller's performance claims</h2><p className="muted">Unverified seller text: {data.performance_claims}</p></>}
      {(data.description || data.pedigree_text) && <><h2>Description</h2><p className="pre">{data.description || data.pedigree_text}</p></>}
      {data.pedigree_url && <p><a href={data.pedigree_url} target="_blank" rel="noopener noreferrer">Pedigree ↗</a></p>}

      <h2>Price history</h2>
      <table><thead><tr><th>Seen</th><th>Bid</th><th>Bids</th></tr></thead>
        <tbody>{data.price_history.map((p, i) => <tr key={i}><td>{when(p.at)}</td><td>{zar(p.current_bid)}</td><td>{p.bid_count ?? "–"}</td></tr>)}</tbody></table>
      {data.bid_history.length > 0 && (
        <>
          <h2>Bid history (as shown on the site)</h2>
          <table><thead><tr><th>When</th><th>Bidder</th><th>Amount</th></tr></thead>
            <tbody>{data.bid_history.map((b, i) => <tr key={i}><td>{when(b.at)}</td><td>{b.bidder}</td><td>{zar(b.amount)}</td></tr>)}</tbody></table>
        </>
      )}
    </section>
  );
}
