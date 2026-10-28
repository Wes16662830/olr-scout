import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { pct } from "../lib/format";
import { useData } from "../lib/useData";

type Claim = { id: number; relation: string; ring: string | null; name: string | null; text: string; origin: string; status: string; confirmed: boolean;
  bird: { ring: string; long_score: number; is_ace: boolean; olr: string; year: number } | null };
type Resp = { lots: { lot: { id: number; title: string; ring: string | null; auction: string; lot_no: number; pedigree_url: string | null; tier: string }; claims: Claim[] }[];
  unread_pedigrees: { id: number; title: string; pedigree_url: string }[] };

function ClaimRow({ c, onSaved }: { c: Claim; onSaved: () => void }) {
  const [ring, setRing] = useState(c.ring || "");
  const [rel, setRel] = useState(c.relation);
  const save = async (extra: Record<string, unknown> = {}) => { await api.put(`/claims/${c.id}`, { ring, relation: rel, ...extra }); onSaved(); };
  return (
    <tr>
      <td><select value={rel} onChange={(e) => setRel(e.target.value)}>{["sire", "dam", "parent", "grandparent", "ancestor"].map((r) => <option key={r}>{r}</option>)}</select></td>
      <td><input value={ring} onChange={(e) => setRing(e.target.value)} /></td>
      <td><span className={`badge st-${c.status}`}>{c.status}</span>{c.confirmed && " ✓"}</td>
      <td className="small">{c.bird ? `${c.bird.olr} ${c.bird.year} · long ${pct(c.bird.long_score)}${c.bird.is_ace ? " · ACE" : ""}` : "not in OLR results"}</td>
      <td className="small">“{c.text}” <i>({c.origin})</i></td>
      <td className="row"><button className="btn" onClick={() => save()}>Confirm</button><button className="btn ghost" onClick={() => save({ reject: true })}>Reject</button></td>
    </tr>
  );
}

export default function PedigreeReview() {
  const { data, reload } = useData<Resp>("/pedigree/review");
  const [ocr, setOcr] = useState<Record<number, string>>({});
  const [add, setAdd] = useState<Record<number, { ring: string; relation: string }>>({});
  const runOcr = async (id: number) => {
    try { const r = await api.post<{ text: string }>(`/lots/${id}/ocr`); setOcr({ ...ocr, [id]: r.text }); reload(); }
    catch (e) { setOcr({ ...ocr, [id]: "OCR failed: " + (e as Error).message }); }
  };
  const addClaim = async (id: number) => {
    const a = add[id];
    if (!a?.ring) return;
    await api.post(`/lots/${id}/claims`, { ring: a.ring, relation: a.relation || "sire" });
    setAdd({ ...add, [id]: { ring: "", relation: "sire" } });
    reload();
  };
  return (
    <section>
      <h1>Pedigree review</h1>
      <p className="muted">Ancestor rings read from seller text, PDFs or OCR. Correct and confirm them here; corrections are kept. A claim only counts as verified when the ring is found with a real OLR result.</p>
      {data?.unread_pedigrees.length ? (
        <div className="panel"><h2>Pedigrees not read yet</h2>
          <ul>{data.unread_pedigrees.map((p) => (
            <li key={p.id}><Link to={`/lot/${p.id}`}>{p.title}</Link> · <a href={p.pedigree_url} target="_blank" rel="noopener noreferrer">view</a> · <button className="btn ghost" onClick={() => runOcr(p.id)}>Read (OCR/PDF)</button>
              {ocr[p.id] && <pre className="ocr">{ocr[p.id]}</pre>}</li>
          ))}</ul></div>
      ) : null}
      {data?.lots.map(({ lot, claims }) => (
        <div key={lot.id} className="panel">
          <h2><Link to={`/lot/${lot.id}`}>{lot.auction} · lot {lot.lot_no} · {lot.ring || lot.title}</Link> <span className={`badge tier-${lot.tier}`}>{lot.tier}</span></h2>
          {lot.pedigree_url && <button className="btn ghost" onClick={() => runOcr(lot.id)}>Re-read pedigree</button>}
          {ocr[lot.id] && <pre className="ocr">{ocr[lot.id]}</pre>}
          <div className="scroll"><table><thead><tr><th>Relation</th><th>Ring</th><th>Status</th><th>OLR result</th><th>Source text</th><th></th></tr></thead>
            <tbody>{claims.map((c) => <ClaimRow key={c.id} c={c} onSaved={reload} />)}</tbody></table></div>
          <div className="row wrap">
            <select value={add[lot.id]?.relation || "sire"} onChange={(e) => setAdd({ ...add, [lot.id]: { ring: add[lot.id]?.ring || "", relation: e.target.value } })}>
              {["sire", "dam", "grandparent"].map((r) => <option key={r}>{r}</option>)}</select>
            <input placeholder="Add ancestor ring" value={add[lot.id]?.ring || ""} onChange={(e) => setAdd({ ...add, [lot.id]: { relation: add[lot.id]?.relation || "sire", ring: e.target.value } })} />
            <button className="btn" onClick={() => addClaim(lot.id)}>Add</button>
          </div>
        </div>
      ))}
      {data && data.lots.length === 0 && !data.unread_pedigrees.length && <p>No ancestor claims on live lots.</p>}
    </section>
  );
}
