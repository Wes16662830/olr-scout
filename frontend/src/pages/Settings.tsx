import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useData } from "../lib/useData";

type Fam = { name: string; aliases: string[]; weight: string };
type Prefs = {
  max_bid: number; near_max_buffer: number; per_lot_max: Record<string, number>; per_family_max: Record<string, number>;
  families: Fam[]; distance_emphasis: string; sex: string; year_min: number | null; year_max: number | null;
  min_races: number; ace_only: boolean; include_tier_c: boolean;
  own: { team_names: string[]; usernames: string[]; exclude_own: boolean };
  weights: Record<string, number>; family_ceiling: number; mismatch_threshold: number; tier_c_cap: number;
  results_seasons: number;
  rank_by: string; breeding_weights: Record<string, number>;
};
type Olr = { id: number; name: string; loft_id: number | null; aliases: string[]; enabled: boolean; auto_discovered: boolean;
  seasons: { id: number; year: number; registered: number | null; ingested_at: string | null; flights: number }[] };

export default function Settings() {
  const { data } = useData<Prefs>("/settings");
  const olrs = useData<Olr[]>("/olrs");
  const [p, setP] = useState<Prefs | null>(null);
  const [msg, setMsg] = useState("");
  const [newFam, setNewFam] = useState("");
  const [newOlr, setNewOlr] = useState({ name: "", loft_id: "", year: "", season_id: "" });
  useEffect(() => { if (data) setP(data); }, [data]);
  if (!p) return <p>Loading…</p>;
  const save = async () => {
    setMsg("Saving…");
    try {
      setP(await api.put<Prefs>("/settings", p));
      setMsg("Saved ✓ — suggestions update within a few seconds.");
    } catch (e) {
      setMsg(`Not saved: ${(e as Error).message}`);
    }
  };
  const setFam = (i: number, patch: Partial<Fam>) => setP({ ...p, families: p.families.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const num = (v: string) => (v === "" ? null : Number(v));
  return (
    <section>
      <h1>Settings</h1>
      <div className="panel">
        <h2>Budget</h2>
        <div className="row wrap">
          <label>Global max bid R <input type="number" value={p.max_bid} onChange={(e) => setP({ ...p, max_bid: Number(e.target.value) })} /></label>
          <label>Warn when within R <input type="number" value={p.near_max_buffer} onChange={(e) => setP({ ...p, near_max_buffer: Number(e.target.value) })} /> of max</label>
        </div>
        <p className="small muted">Per-lot max overrides (lot id → R): {Object.entries(p.per_lot_max).map(([k, v]) => `#${k}: R${v}`).join(", ") || "none"}.
          Edit as JSON: <input className="wide" defaultValue={JSON.stringify(p.per_lot_max)} onBlur={(e) => { try { setP({ ...p, per_lot_max: JSON.parse(e.target.value || "{}") }); } catch { setMsg("per-lot max: invalid JSON"); } }} /></p>
      </div>

      <div className="panel">
        <h2>Families / bloodlines</h2>
        <p className="small muted">Matched in seller, bloodline, title, description and pedigree text, with aliases (accents ignored: Thoné = Thone). Avoid removes a lot from suggestions.</p>
        <table><thead><tr><th>Name</th><th>Aliases</th><th>Preference</th><th>Max R</th><th></th></tr></thead>
          <tbody>{p.families.map((f, i) => (
            <tr key={f.name + i}>
              <td>{f.name}</td>
              <td><input value={f.aliases.join(", ")} onChange={(e) => setFam(i, { aliases: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></td>
              <td><select value={f.weight} onChange={(e) => setFam(i, { weight: e.target.value })}>{["love", "like", "neutral", "avoid"].map((w) => <option key={w}>{w}</option>)}</select></td>
              <td><input type="number" value={p.per_family_max[f.name] ?? ""} onChange={(e) => {
                const m = { ...p.per_family_max }; if (e.target.value === "") delete m[f.name]; else m[f.name] = Number(e.target.value); setP({ ...p, per_family_max: m });
              }} /></td>
              <td><button className="btn ghost" onClick={() => setP({ ...p, families: p.families.filter((_, j) => j !== i) })}>✕</button></td>
            </tr>
          ))}</tbody></table>
        <div className="row"><input placeholder="Add family (free text)" value={newFam} onChange={(e) => setNewFam(e.target.value)} />
          <button className="btn ghost" onClick={() => { if (newFam) { setP({ ...p, families: [...p.families, { name: newFam, aliases: [newFam.toLowerCase()], weight: "like" }] }); setNewFam(""); } }}>Add</button></div>
      </div>

      <div className="panel">
        <h2>Type</h2>
        <div className="row wrap">
          <label>Emphasis <select value={p.distance_emphasis} onChange={(e) => setP({ ...p, distance_emphasis: e.target.value })}>
            <option value="distance">distance (long races)</option><option value="middle">middle distance (all races)</option><option value="balanced">balanced</option></select></label>
          <label>Sex <select value={p.sex} onChange={(e) => setP({ ...p, sex: e.target.value })}><option>any</option><option>cock</option><option>hen</option></select></label>
          <label>Year from <input type="number" value={p.year_min ?? ""} onChange={(e) => setP({ ...p, year_min: num(e.target.value) })} /></label>
          <label>to <input type="number" value={p.year_max ?? ""} onChange={(e) => setP({ ...p, year_max: num(e.target.value) })} /></label>
          <label>Min races <input type="number" value={p.min_races} onChange={(e) => setP({ ...p, min_races: Number(e.target.value) })} /></label>
          <label><input type="checkbox" checked={p.ace_only} onChange={(e) => setP({ ...p, ace_only: e.target.checked })} /> aces only</label>
          <label><input type="checkbox" checked={p.include_tier_c} onChange={(e) => setP({ ...p, include_tier_c: e.target.checked })} /> include Tier C (seller-claimed)</label>
        </div>
      </div>

      <div className="panel">
        <h2>Own birds</h2>
        <div className="row wrap">
          <label>Team names <input className="wide" value={p.own.team_names.join("; ")} onChange={(e) => setP({ ...p, own: { ...p.own, team_names: e.target.value.split(";").map((s) => s.trim()).filter(Boolean) } })} /></label>
          <label>Site usernames <input value={p.own.usernames.join("; ")} onChange={(e) => setP({ ...p, own: { ...p.own, usernames: e.target.value.split(";").map((s) => s.trim()).filter(Boolean) } })} /></label>
          <label><input type="checkbox" checked={p.own.exclude_own} onChange={(e) => setP({ ...p, own: { ...p.own, exclude_own: e.target.checked } })} /> hide my own lots</label>
        </div>
      </div>

      <div className="panel">
        <h2>Ranking</h2>
        <div className="row wrap">
          <label>Order suggestions by
            <select value={p.rank_by} onChange={(e) => setP({ ...p, rank_by: e.target.value })}>
              <option value="racing">Racing score (how the bird raced)</option>
              <option value="breeding">Breeding score (offspring, siblings, parents)</option>
            </select>
          </label>
        </div>
        <h3>Breeding score weights</h3>
        <p className="small muted">Only used when a lot has offspring, sibling or verified-parent evidence.</p>
        <div className="row wrap">{Object.entries(p.breeding_weights || {}).map(([k, v]) => (
          <label key={k}>{k} <input type="number" value={v} onChange={(e) => setP({ ...p, breeding_weights: { ...p.breeding_weights, [k]: Number(e.target.value) } })} /></label>
        ))}</div>
        <h2>Racing score weights (Tier A)</h2>
        <div className="row wrap">{Object.entries(p.weights).map(([k, v]) => (
          <label key={k}>{k} <input type="number" value={v} onChange={(e) => setP({ ...p, weights: { ...p.weights, [k]: Number(e.target.value) } })} /></label>
        ))}</div>
        <div className="row wrap">
          <label>Family rate for full marks <input type="number" step="0.01" value={p.family_ceiling} onChange={(e) => setP({ ...p, family_ceiling: Number(e.target.value) })} /></label>
          <label>Mismatch if best race worse than <input type="number" step="0.01" value={p.mismatch_threshold} onChange={(e) => setP({ ...p, mismatch_threshold: Number(e.target.value) })} /></label>
        </div>
      </div>
      <button className="btn" onClick={save}>Save settings</button> <span className="muted">{msg}</span>

      <div className="panel">
        <h2>OLR registry</h2>
        <div className="row wrap">
          <label>OLR seasons to download per OLR
            <input type="number" min={1} max={10} value={p.results_seasons}
              onChange={(e) => setP({ ...p, results_seasons: Math.max(1, Number(e.target.value) || 1) })} />
          </label>
          <span className="small muted">Newest seasons with races. 2 covers the birds on sale; 4–5 also verifies most
            parents (they raced 2–4 years earlier), so more lots reach Tier B. Click Save settings, then Ingest on Sources.</span>
        </div>
        <p className="small muted">Name → Benzing loft id → seasons. Auto-discovered lofts arrive disabled; enable the ones that are real OLRs.</p>
        <table><thead><tr><th>OLR</th><th>Loft id</th><th>Seasons (year: id, birds)</th><th>Enabled</th></tr></thead>
          <tbody>{olrs.data?.map((o) => (
            <tr key={o.id}><td>{o.name}{o.auto_discovered && <span className="badge">auto</span>}</td><td>{o.loft_id ?? "–"}</td>
              <td className="small">{o.seasons.map((s) => `${s.year}: ${s.id}${s.registered ? ` (${s.registered})` : ""}${s.ingested_at ? "" : " – not ingested"}`).join(" · ")}</td>
              <td><input type="checkbox" checked={o.enabled} onChange={async (e) => {
                const enabled = e.target.checked;
                olrs.setData((olrs.data || []).map((x) => (x.id === o.id ? { ...x, enabled } : x)));
                try { await api.put("/olrs", { id: o.id, enabled }); setMsg(`${o.name} ${enabled ? "on" : "off"} ✓`); }
                catch (err) { setMsg(`${o.name} not changed: ${(err as Error).message}`); }
                olrs.reload();
              }} /></td></tr>
          ))}</tbody></table>
        <div className="row wrap">
          <input placeholder="OLR name" value={newOlr.name} onChange={(e) => setNewOlr({ ...newOlr, name: e.target.value })} />
          <input placeholder="Loft id" value={newOlr.loft_id} onChange={(e) => setNewOlr({ ...newOlr, loft_id: e.target.value })} />
          <input placeholder="Season year" value={newOlr.year} onChange={(e) => setNewOlr({ ...newOlr, year: e.target.value })} />
          <input placeholder="Season id" value={newOlr.season_id} onChange={(e) => setNewOlr({ ...newOlr, season_id: e.target.value })} />
          <button className="btn ghost" onClick={async () => {
            await api.put("/olrs", { name: newOlr.name, loft_id: newOlr.loft_id ? Number(newOlr.loft_id) : null, aliases: [newOlr.name.toLowerCase()], enabled: true,
              seasons: newOlr.year && newOlr.season_id ? { [newOlr.year]: Number(newOlr.season_id) } : {} });
            setNewOlr({ name: "", loft_id: "", year: "", season_id: "" }); olrs.reload();
          }}>Save OLR</button>
        </div>
      </div>
    </section>
  );
}
