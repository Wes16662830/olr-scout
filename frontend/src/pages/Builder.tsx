import { useState } from "react";
import { api } from "../lib/api";
import { pct, zar } from "../lib/format";
import { useData } from "../lib/useData";

type Item = { lot_id: number; label: string; sex: string; tier: string; families: string[]; strength: number; current: number; max_bid: number; url: string };
type FamRec = { family: string; entries: number; aces: number; ace_rate: number | null; finalists: number; small_sample: boolean;
  seasons: { olr: string; year: number; entries: number; aces: number; ace_rate: number }[]; best_long: { ring: string; long_score: number; year: number }[] };
type Plan = { items: Item[]; total_max: number; budget: number; notes: string[]; excluded: { lot_id: number; reason: string }[];
  pairs: { cock: string; hen: string; relation: string; cross: boolean; strength: number; nick: string | null }[];
  gaps: { family: string; have: { cock: number; hen: number }; planned: { cock: number; hen: number }; target_each: number; fill: { lot_id: number; label: string; sex: string; max_bid: number; url: string }[] }[];
  families: FamRec[] };
type Inv = { id: number; ring: string; sex: string | null; family: string | null; name: string | null; sire: string | null; dam: string | null; grandparents: string[] };

export default function Builder() {
  const fams = useData<{ families: { family: string; entries: number; ace_rate: number }[] }>("/families?min_entries=5&limit=200");
  const olrs = useData<{ name: string; enabled: boolean }[]>("/olrs");
  const inv = useData<Inv[]>("/inventory");
  const [goal, setGoal] = useState({ pairs: 6, budget: 60000, cocks: 6, hens: 6, core_families: [] as string[], olrs: [] as string[], allow_line_bred: true });
  const [plan, setPlan] = useState<Plan | null>(null);
  const [err, setErr] = useState("");
  const [newBird, setNewBird] = useState({ ring: "", sex: "cock", family: "", name: "", sire: "", dam: "", grandparents: "" });

  const run = async () => {
    setErr("");
    try { setPlan(await api.post<Plan>("/builder/plan", goal)); } catch (e) { setErr((e as Error).message); }
  };
  const toggle = (arr: string[], v: string, max = 99) => arr.includes(v) ? arr.filter((x) => x !== v) : arr.length < max ? [...arr, v] : arr;
  const addBird = async () => {
    await api.post("/inventory", { ...newBird, grandparents: newBird.grandparents.split(",").map((s) => s.trim()).filter(Boolean) });
    setNewBird({ ring: "", sex: "cock", family: "", name: "", sire: "", dam: "", grandparents: "" });
    inv.reload();
  };

  return (
    <section>
      <h1>Family Builder</h1>
      <p className="muted">Only verified OLR data drives this plan (Tier A/B lots). Seller claims never do. OLR wins stay largely luck (about 37% of entries reach the Final), so the aim is volume of well-bred birds from families with a real record.</p>
      <div className="panel">
        <h2>Goal</h2>
        <div className="row wrap">
          <label>Pairs <input type="number" value={goal.pairs} onChange={(e) => setGoal({ ...goal, pairs: +e.target.value, cocks: +e.target.value, hens: +e.target.value })} /></label>
          <label>Cocks <input type="number" value={goal.cocks} onChange={(e) => setGoal({ ...goal, cocks: +e.target.value })} /></label>
          <label>Hens <input type="number" value={goal.hens} onChange={(e) => setGoal({ ...goal, hens: +e.target.value })} /></label>
          <label>Total budget R <input type="number" value={goal.budget} onChange={(e) => setGoal({ ...goal, budget: +e.target.value })} /></label>
          <label><input type="checkbox" checked={goal.allow_line_bred} onChange={(e) => setGoal({ ...goal, allow_line_bred: e.target.checked })} /> allow line-bred to my birds</label>
        </div>
        <h3>OLRs to win</h3>
        <div className="chips">{olrs.data?.filter((o) => o.enabled).map((o) => (
          <button key={o.name} className={goal.olrs.includes(o.name) ? "chip on" : "chip"} onClick={() => setGoal({ ...goal, olrs: toggle(goal.olrs, o.name) })}>{o.name}</button>
        ))}</div>
        <h3>Core families (pick 1–3)</h3>
        <div className="chips">{fams.data?.families.slice(0, 60).map((f) => (
          <button key={f.family} className={goal.core_families.includes(f.family) ? "chip on" : "chip"}
            onClick={() => setGoal({ ...goal, core_families: toggle(goal.core_families, f.family, 3) })}>
            {f.family} <small>{pct(f.ace_rate)} · n={f.entries}</small></button>
        ))}</div>
        {fams.data?.families.length === 0 && <p className="muted">No family records yet: ingest OLR results first (Sources).</p>}
        <button className="btn" onClick={run}>Build plan</button> {err && <span className="error">{err}</span>}
      </div>

      {plan && (
        <>
          {plan.families.map((f) => (
            <div key={f.family} className="panel">
              <h2>{f.family} {f.small_sample && <span className="badge warn">small sample (&lt;20 entries)</span>}</h2>
              <p>{f.aces} aces from {f.entries} entries · ace rate {pct(f.ace_rate)} · {f.finalists} finalists</p>
              <p className="small">{f.seasons.map((s) => `${s.olr} ${s.year}: ${s.aces}/${s.entries} (${pct(s.ace_rate)})`).join(" · ")}</p>
              <p className="small">Best long-race birds: {f.best_long.map((b) => `${b.ring} ${pct(b.long_score)} (${b.year})`).join(", ") || "–"}</p>
            </div>
          ))}
          <div className="panel">
            <h2>Shopping plan</h2>
            <p><b>Buy these {plan.items.length} lots, total max {zar(plan.total_max)}</b> (budget {zar(plan.budget)})</p>
            <table><thead><tr><th>Lot</th><th>Sex</th><th>Tier</th><th>Family</th><th>Now</th><th>Max bid</th><th></th></tr></thead>
              <tbody>{plan.items.map((i) => <tr key={i.lot_id}><td>{i.label}</td><td>{i.sex}</td><td>{i.tier}</td><td>{i.families.join(", ")}</td><td>{zar(i.current)}</td><td><b>{zar(i.max_bid)}</b></td><td><a href={i.url} target="_blank" rel="noopener noreferrer">Open lot ↗</a></td></tr>)}</tbody></table>
            {plan.notes.map((n) => <p key={n} className="muted">{n}</p>)}
            {plan.excluded.length > 0 && <details><summary>{plan.excluded.length} lots left out</summary><ul>{plan.excluded.map((e) => <li key={e.lot_id}>lot {e.lot_id}: {e.reason}</li>)}</ul></details>}
          </div>
          <div className="panel">
            <h2>Gap view</h2>
            {plan.gaps.map((g) => (
              <div key={g.family}>
                <p>You have <b>{g.have.cock} cocks, {g.have.hen} hens</b> from {g.family}; plan adds {g.planned.cock} cocks, {g.planned.hen} hens (target {g.target_each} each).</p>
                {g.fill.length > 0 && <p className="small">Lots that fill the gap: {g.fill.map((f) => `${f.label} (${f.sex}, max ${zar(f.max_bid)})`).join(" · ")}</p>}
              </div>
            ))}
          </div>
          <div className="panel">
            <h2>Pair suggestions</h2>
            <table><thead><tr><th>Cock</th><th>Hen</th><th>Relation</th><th>Type</th><th>Strength</th></tr></thead>
              <tbody>{plan.pairs.slice(0, 30).map((p, i) => (
                <tr key={i} className={p.relation === "too close" ? "bad" : ""}><td>{p.cock}</td><td>{p.hen}</td>
                  <td><span className={`badge rel-${p.relation.replace(" ", "-")}`}>{p.relation}</span></td>
                  <td>{p.cross ? `cross${p.nick ? " — " + p.nick : ""}` : "same family"}</td><td>{p.strength.toFixed(2)}</td></tr>
              ))}</tbody></table>
          </div>
        </>
      )}

      <div className="panel">
        <h2>My loft inventory</h2>
        <p className="muted">Your own breeders, so the app does not recommend birds too closely related to them.</p>
        <table><thead><tr><th>Ring</th><th>Sex</th><th>Family</th><th>Sire</th><th>Dam</th><th>Grandparents</th><th></th></tr></thead>
          <tbody>{inv.data?.map((b) => (
            <tr key={b.id}><td>{b.ring} {b.name}</td><td>{b.sex}</td><td>{b.family}</td><td>{b.sire}</td><td>{b.dam}</td><td className="small">{b.grandparents?.join(", ")}</td>
              <td><button className="btn ghost" onClick={async () => { await api.del(`/inventory/${b.id}`); inv.reload(); }}>Delete</button></td></tr>
          ))}</tbody></table>
        <div className="row wrap">
          <input placeholder="Ring" value={newBird.ring} onChange={(e) => setNewBird({ ...newBird, ring: e.target.value })} />
          <select value={newBird.sex} onChange={(e) => setNewBird({ ...newBird, sex: e.target.value })}><option>cock</option><option>hen</option></select>
          <input placeholder="Family (OLR team)" value={newBird.family} onChange={(e) => setNewBird({ ...newBird, family: e.target.value })} />
          <input placeholder="Name" value={newBird.name} onChange={(e) => setNewBird({ ...newBird, name: e.target.value })} />
          <input placeholder="Sire ring" value={newBird.sire} onChange={(e) => setNewBird({ ...newBird, sire: e.target.value })} />
          <input placeholder="Dam ring" value={newBird.dam} onChange={(e) => setNewBird({ ...newBird, dam: e.target.value })} />
          <input placeholder="Grandparents (comma-separated rings)" value={newBird.grandparents} onChange={(e) => setNewBird({ ...newBird, grandparents: e.target.value })} />
          <button className="btn" disabled={!newBird.ring} onClick={addBird}>Add</button>
        </div>
      </div>
    </section>
  );
}
