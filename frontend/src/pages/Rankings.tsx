import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { zar } from "../lib/format";
import { useData } from "../lib/useData";

type Race = { no: number; name: string; km: number | null; final: boolean; date: string | null };
type SeasonRaces = { season_id: number; olr: string; year: number; races: Race[] };
type Row = {
  rank: number; ring: string; name: string | null; team: string | null; value: number; gap: number | null; races_home: number;
  jackets: { blue?: number; green?: number; brown?: number } | null;
  lots: { id: number; lot_no: number | null; auction: string | null; price: number | null; has_bid: boolean }[];
};
type Result = { olr: string; season: number; measure: string; races: number[]; ranked: number; on_auction: number; rows: Row[] };

const hms = (min: number) => {
  const s = Math.round(min * 60);
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}' ${String(s % 60).padStart(2, "0")}"`;
};

/** What-if standings: rank an OLR season over any chosen races (e.g. Blue after race 9, no final). */
export default function Rankings() {
  const seasons = useData<SeasonRaces[]>("/rankings/seasons");
  const [sid, setSid] = useState<number | null>(null);
  const season = seasons.data?.find((x) => x.season_id === sid) ?? seasons.data?.[0];
  const [chosen, setChosen] = useState<number[]>([]);
  const [measure, setMeasure] = useState<"time" | "result">("time");
  const [onlyAuction, setOnlyAuction] = useState(false);
  const [label, setLabel] = useState("All races (Blue jacket)");
  const [msg, setMsg] = useState("");
  const all = useMemo(() => season?.races.map((r) => r.no) ?? [], [season]);
  useEffect(() => { setChosen(all); setLabel("All races (Blue jacket)"); }, [all]);

  const last = all[all.length - 1];
  const presets: [string, number[]][] = season ? [
    ["All races (Blue jacket)", all],
    ["Races 1–5 (Green jacket)", all.filter((n) => n <= 5)],
    ["Races 6–10 (Brown jacket)", all.filter((n) => n >= 6 && n <= 10)],
    ...(season.races.some((r) => r.final) ? [[`Before the final (races 1–${last - 1})`, all.filter((n) => n !== last)] as [string, number[]]] : []),
  ] : [];
  const path = season && chosen.length
    ? `/rankings?season_id=${season.season_id}&races=${chosen.join(",")}&measure=${measure}&on_auction=${onlyAuction}&limit=150`
    : null;
  const res = useData<Result>(path);
  const toggle = (n: number) => { setChosen((c) => (c.includes(n) ? c.filter((x) => x !== n) : [...c, n].sort((a, b) => a - b))); setLabel("Custom races"); };
  const useForSuggestions = async () => {
    if (!season) return;
    const p = await api.get<Record<string, unknown>>("/settings");
    const scenario = { season_id: season.season_id, races: chosen, measure,
      label: `${season.olr} ${season.year}: ${label} — ${measure === "time" ? "total flying time" : "OLR Scout result"}` };
    await api.put("/settings", { ...p, rank_by: "scenario", scenario });
    setMsg(`Suggestions are now ordered by: ${scenario.label}.`);
  };

  if (seasons.data && !seasons.data.length) return <section><h1>Rankings</h1><p>No OLR results downloaded yet (Sources → Ingest OLR results).</p></section>;
  return (
    <section>
      <h1>Rankings — what if?</h1>
      <p className="muted">Rank a season over any races you choose: before the final, a single race, the jacket races…
        Birds on auction now are marked, with their lot.</p>
      <div className="panel">
        <div className="row wrap">
          <label>Season
            <select value={season?.season_id ?? ""} onChange={(e) => setSid(Number(e.target.value))}>
              {seasons.data?.map((x) => <option key={x.season_id} value={x.season_id}>{x.olr} {x.year}</option>)}
            </select>
          </label>
          <label>Rank by
            <select value={measure} onChange={(e) => setMeasure(e.target.value as "time" | "result")}>
              <option value="time">Total flying time (jacket rules)</option>
              <option value="result">OLR Scout result (placing + time behind winner)</option>
            </select>
          </label>
          <label><input type="checkbox" checked={onlyAuction} onChange={(e) => setOnlyAuction(e.target.checked)} /> only birds on auction now</label>
        </div>
        <div className="row wrap">
          {presets.map(([name, races]) => (
            <button key={name} className={`chip ${label === name ? "on" : ""}`} onClick={() => { setChosen(races); setLabel(name); }}>{name}</button>
          ))}
        </div>
        <div className="row wrap races-pick">
          {season?.races.map((r) => (
            <label key={r.no} className={`chip ${chosen.includes(r.no) ? "on" : ""}`} title={`${r.name}${r.km ? ` · ${r.km} km` : ""}`}>
              <input type="checkbox" checked={chosen.includes(r.no)} onChange={() => toggle(r.no)} />
              {r.final ? "Final" : `R${r.no}`}{r.km ? ` ${Math.round(r.km)} km` : ""}
            </label>
          ))}
          {chosen.length === 1 && <span className="small muted">one race: its result order</span>}
        </div>
        <p className="small muted">
          {measure === "time"
            ? "Total flying time, as AfrikaPro ranks its jackets: home in every chosen race; no race counts slower than 500 m/min. Matches the official 2026 Blue, Green and Brown top 50 place for place; lower down a bird that stayed out overnight can differ by up to an hour."
            : "OLR Scout's race result: half placing among the starters, half time behind the winner, averaged over the chosen races; a missed race counts as last."}
        </p>
        <button className="btn" onClick={useForSuggestions} disabled={!chosen.length}>Order my Suggestions by this</button>{" "}
        <span className="small muted">{msg}</span>
      </div>
      {res.error && <p className="error">{res.error}</p>}
      {res.loading && !res.data && <p>Working it out…</p>}
      {res.data && (
        <>
          <p className="small muted">{res.data.ranked} birds ranked{measure === "time" ? " (home in every chosen race)" : ""} ·
            {" "}{res.data.on_auction} of them on auction now{onlyAuction ? " (showing only those)" : ""}.</p>
          <div className="scroll"><table className="rankings">
            <thead><tr><th>#</th><th>Bird</th><th>Entrant</th><th>{measure === "time" ? "Total time" : "Result"}</th>
              <th>{measure === "time" ? "Behind leader" : ""}</th><th>Official jackets</th><th>On auction</th></tr></thead>
            <tbody>{res.data.rows.map((r) => (
              <tr key={r.ring} className={r.lots.length ? "for-sale" : ""}>
                <td>{r.rank}</td>
                <td><b>{r.ring}</b>{r.name ? <div className="small muted">“{r.name}”</div> : null}</td>
                <td className="small">{r.team}</td>
                <td>{measure === "time" ? hms(r.value) : `top ${(r.value * 100).toFixed(1)}%`}</td>
                <td className="small muted">{measure === "time" && r.gap ? `+${hms(r.gap)}` : ""}</td>
                <td className="small">{r.jackets && Object.keys(r.jackets).length
                  ? (["blue", "brown", "green"] as const).filter((k) => r.jackets![k]).map((k) => (
                      <span key={k} className={`jacket jacket-${k}${(r.jackets![k] ?? 999) <= 50 ? " top" : ""}`}>{k[0].toUpperCase() + k.slice(1)} {r.jackets![k]}</span>))
                  : <span className="muted">–</span>}</td>
                <td>{r.lots.map((l) => (
                  <div key={l.id}><Link to={`/lot/${l.id}`}>Lot {l.lot_no ?? "?"}</Link> <span className="small">{zar(l.price)}{l.has_bid ? "" : " start"}</span></div>
                ))}</td>
              </tr>
            ))}</tbody>
          </table></div>
        </>
      )}
    </section>
  );
}
