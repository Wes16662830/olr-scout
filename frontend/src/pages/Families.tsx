import { useState } from "react";
import { pct, zar } from "../lib/format";
import { useData } from "../lib/useData";

type Fam = { family: string; entries: number; aces: number; finalists: number; ace_rate: number; small_sample: boolean;
  seasons: { year: number; olr: string; entries: number; aces: number; ace_rate: number }[] };
type Resp = { families: Fam[]; persistence: { from: number; to: number; families: number; r: number | null }[];
  top_parents: { ring: string; name: string | null; raced: string | null; offspring_named: number; offspring_raced: number;
    aces: number; ace_rate: number; mean_long: number; strength: number; best: { ring: string; olr: string; season: number; is_ace: boolean }[] }[];
  leaders: { breeders: { seller: string; sold_raced: number; aces: number; ace_rate: number }[]; buyers: { bidder: string; lots: number; spent: number | null }[] } };

export default function Families() {
  const [olr, setOlr] = useState("");
  const [minN, setMinN] = useState(5);
  const { data, error } = useData<Resp>(`/families?min_entries=${minN}${olr ? `&olr=${encodeURIComponent(olr)}` : ""}`);
  const olrs = useData<{ name: string }[]>("/olrs");
  return (
    <section>
      <h1>Families</h1>
      <p className="muted">OLR team families (I/II/A/B/(Single) suffixes merged; “A &amp; B” = “B &amp; A”). Ace = top 5% of registered birds on long-race score. Rates are shrunk toward the 5% field rate with a 20-entry prior.</p>
      <div className="row wrap">
        <select value={olr} onChange={(e) => setOlr(e.target.value)}>
          <option value="">All OLRs</option>
          {olrs.data?.map((o) => <option key={o.name}>{o.name}</option>)}
        </select>
        <label>Min entries <input type="number" value={minN} onChange={(e) => setMinN(Number(e.target.value))} /></label>
      </div>
      {error && <div className="error">{error}</div>}
      {data && data.persistence.length > 0 && (
        <p>Year-to-year persistence (Pearson r of family ace rate): {data.persistence.map((p) => `${p.from}→${p.to}: ${p.r === null ? "n/a" : p.r.toFixed(2)} (${p.families} families)`).join(" · ")}</p>
      )}
      <div className="scroll"><table>
        <thead><tr><th>Family</th><th>Entries</th><th>Aces</th><th>Finalists</th><th>Ace rate</th><th>By season</th></tr></thead>
        <tbody>{data?.families.map((f) => (
          <tr key={f.family}><td>{f.family}{f.small_sample && <span className="badge warn">small sample</span>}</td><td>{f.entries}</td><td>{f.aces}</td><td>{f.finalists}</td>
            <td>{pct(f.ace_rate)}</td><td className="small">{f.seasons.map((s) => `${s.olr} ${s.year}: ${s.aces}/${s.entries}`).join(" · ")}</td></tr>
        ))}</tbody>
      </table></div>
      {data?.families.length === 0 && <p>No results ingested yet. Run a results ingest from Sources.</p>}
      <div className="panel">
        <h2>Proven parents (offspring in OLR results)</h2>
        <p className="small muted">Built from the sire/dam rings that auction listings name for birds that raced. Grows with
          every auction OLR Scout watches; small numbers are luck as much as genes.</p>
        {data && data.top_parents.length === 0 && <p className="muted">No parent has 2+ offspring in the results yet.</p>}
        {data && data.top_parents.length > 0 && (
          <div className="scroll"><table>
            <thead><tr><th>Parent</th><th>Raced</th><th>Offspring raced</th><th>Aces</th><th>Ace rate</th><th>Avg long</th><th>Best offspring</th></tr></thead>
            <tbody>{data.top_parents.map((p) => (
              <tr key={p.ring}><td><b>{p.ring}</b>{p.name ? ` “${p.name}”` : ""}</td><td>{p.raced ?? "not in OLR results"}</td>
                <td>{p.offspring_raced} of {p.offspring_named}</td><td>{p.aces}</td><td>{pct(p.ace_rate)}</td><td>top {pct(p.mean_long)}</td>
                <td className="small">{p.best.map((b) => `${b.ring}${b.is_ace ? " (ace)" : ""}`).join(", ")}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      <div className="row wrap" style={{ alignItems: "flex-start" }}>
        <div className="panel" style={{ flex: 1, minWidth: 280 }}>
          <h2>Breeder leaders</h2>
          <p className="small muted">Sellers whose sold birds later raced in an OLR.</p>
          <table><thead><tr><th>Seller</th><th>Raced</th><th>Aces</th><th>Rate</th></tr></thead>
            <tbody>{data?.leaders.breeders.map((b) => <tr key={b.seller}><td>{b.seller}</td><td>{b.sold_raced}</td><td>{b.aces}</td><td>{pct(b.ace_rate)}</td></tr>)}</tbody></table>
        </div>
        <div className="panel" style={{ flex: 1, minWidth: 280 }}>
          <h2>Buyer leaders</h2>
          <p className="small muted">Winning bidders on closed lots, as the sites show them.</p>
          <table><thead><tr><th>Bidder</th><th>Lots</th><th>Spent</th></tr></thead>
            <tbody>{data?.leaders.buyers.map((b) => <tr key={b.bidder}><td>{b.bidder}</td><td>{b.lots}</td><td>{zar(b.spent)}</td></tr>)}</tbody></table>
        </div>
      </div>
    </section>
  );
}
