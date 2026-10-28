import { useState } from "react";
import { api } from "../lib/api";
import { when } from "../lib/format";
import { useData } from "../lib/useData";

type S = { key: string; name: string; base_url: string; verified: boolean; status: string; last_run: string | null; last_success: string | null; lot_count: number; message: string; detail: Record<string, unknown> };

export default function Sources() {
  const { data, reload } = useData<S[]>("/sources", 30_000);
  const [busy, setBusy] = useState("");
  const run = async (path: string, body: unknown, label: string) => {
    setBusy(label + "…");
    try {
      const r = await api.post<{ message?: string }>(path, body);
      setBusy(`${label}: ${r.message || "started"}`);
    } catch (e) { setBusy(`${label}: ${(e as Error).message}`); }
    reload();
  };
  return (
    <section>
      <h1>Sources</h1>
      <p className="muted">Read-only: OLR Scout never logs in or bids. Each source runs on its own; a blocked site is marked degraded and is not retried around its bot protection.</p>
      <div className="row wrap">
        <button className="btn" onClick={() => run("/sources/refresh", {}, "Refresh all")}>Refresh lots now</button>
        <button className="btn ghost" onClick={() => run("/results/ingest", {}, "Results ingest")}>Ingest OLR results now</button>
        <span className="muted">{busy}</span>
      </div>
      <div className="scroll"><table>
        <thead><tr><th>Source</th><th>Status</th><th>Lots / birds</th><th>Last run</th><th>Last success</th><th>Notes</th></tr></thead>
        <tbody>{data?.map((s) => (
          <tr key={s.key}>
            <td><a href={s.base_url} target="_blank" rel="noopener noreferrer">{s.name}</a>{!s.verified && <div className="small muted">not yet verified on live pages</div>}</td>
            <td><span className={`badge status-${s.status.replace(/ /g, "-")}`}>{s.status}</span></td>
            <td>{s.lot_count}</td><td>{when(s.last_run)}</td><td>{when(s.last_success)}</td>
            <td className="small">{s.message}
              {s.detail && Object.keys(s.detail).length > 0 && <details><summary>detail</summary><pre className="ocr">{JSON.stringify(s.detail, null, 2)}</pre></details>}</td>
            <td><button className="btn ghost" onClick={() => run("/sources/refresh", { only: [s.key] }, `Refresh ${s.key}`)} disabled={s.key === "benzing"}>Run</button></td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}
