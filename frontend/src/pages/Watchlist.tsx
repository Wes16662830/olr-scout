import { useState } from "react";
import LotCard from "../components/LotCard";
import { api, LotCard as Lot } from "../lib/api";
import { when } from "../lib/format";
import { useData } from "../lib/useData";
import { enablePush } from "../push";

type W = { watch: { id: number; near_max_within: number | null; closes_in: number[]; above_max: boolean; auto?: boolean }; lot: Lot };
type A = { id: number; lot_id: number; kind: string; message: string; at: string; read: boolean };

export default function Watchlist() {
  const wl = useData<W[]>("/watchlist", 30_000);
  const al = useData<A[]>("/alerts", 30_000);
  const [pushMsg, setPushMsg] = useState("");
  const save = async (w: W, patch: Partial<W["watch"]>) => {
    await api.post(`/lots/${w.lot.id}/watch`, { ...w.watch, ...patch });
    wl.reload();
  };
  return (
    <section>
      <h1>Watchlist</h1>
      <div className="row wrap">
        <button className="btn ghost" onClick={async () => setPushMsg(await enablePush())}>Enable phone notifications</button>
        <span className="muted">{pushMsg}</span>
      </div>
      {wl.data?.length === 0 && <p>Nothing watched yet. Tap “Watch” on a lot — lots you bid on are added automatically.</p>}
      {wl.data?.map((w) => (
        <div key={w.watch.id} className="watch">
          {w.watch.auto && <div className="small muted">Added automatically because you bid on it.</div>}
          <LotCard lot={w.lot} onWatch={wl.reload} />
          <div className="rules row wrap">
            <label>Warn within R
              <input type="number" value={w.watch.near_max_within ?? ""} placeholder="global"
                onChange={(e) => save(w, { near_max_within: e.target.value === "" ? null : Number(e.target.value) })} />
              of max
            </label>
            {[30, 10].map((m) => (
              <label key={m}><input type="checkbox" checked={w.watch.closes_in.includes(m)}
                onChange={(e) => save(w, { closes_in: e.target.checked ? [...w.watch.closes_in, m] : w.watch.closes_in.filter((x) => x !== m) })} />
                closes in {m} min</label>
            ))}
            <label><input type="checkbox" checked={w.watch.above_max} onChange={(e) => save(w, { above_max: e.target.checked })} /> price above max</label>
            <button className="btn ghost" onClick={async () => { await api.del(`/lots/${w.lot.id}/watch`); wl.reload(); }}>Remove</button>
          </div>
        </div>
      ))}
      <h2>Alerts</h2>
      <button className="btn ghost" onClick={async () => { await api.post("/alerts/read"); al.reload(); }}>Mark all read</button>
      <ul className="alerts">
        {al.data?.map((a) => <li key={a.id} className={a.read ? "read" : ""}><b>{when(a.at)}</b> {a.message}</li>)}
      </ul>
    </section>
  );
}
