import { useState } from "react";
import { api } from "../lib/api";
import { when } from "../lib/format";
import { useData } from "../lib/useData";

type Progress = { running?: boolean; phase?: string; auction?: string; done?: number; total?: number | null; auctions?: number; auctions_done?: number;
  olr?: string; season?: number; race?: number; races?: number; race_name?: string; seasons_done?: number; error?: string };

function ingestText(p?: Progress): string | null {
  if (!p) return null;
  if (!p.running) return p.phase === "failed" ? `last run failed: ${p.error ?? ""}` : null;
  const where = [p.olr, p.season].filter(Boolean).join(" ");
  const race = p.phase === "reading race results" && p.races ? ` — race ${p.race} of ${p.races}` : "";
  const done = p.seasons_done ? ` · ${p.seasons_done} season(s) saved` : "";
  return `${where ? where + ": " : ""}${p.phase ?? "working"}${race}${done}`;
}
type S = { key: string; name: string; base_url: string; verified: boolean; status: string; last_run: string | null; last_success: string | null; lot_count: number; message: string; detail: Record<string, unknown>; progress?: Progress };

function progressText(p?: Progress): string | null {
  if (!p?.running) return null;
  if (p.phase === "listing auctions") return "reading the auction list…";
  if (p.phase === "reading lots") {
    const of = p.total ? ` of ~${p.total}` : "";
    const auc = p.auctions ? ` · auction ${Math.min((p.auctions_done ?? 0) + 1, p.auctions)} of ${p.auctions}` : "";
    return `reading lots: ${p.done ?? 0}${of} in “${p.auction ?? ""}”${auc}`;
  }
  return p.phase || "working…";
}

export default function Sources() {
  const { data, reload } = useData<S[]>("/sources", 3_000);
  const running = data?.some((s) => s.key !== "benzing" && s.progress?.running);
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
      {running && (
        <p className="banner">
          Reading the sites now. Each site gets at most one request per second, so the first full read can take
          several minutes; later refreshes only re-open lots whose price changed or that close soon. Lots appear on
          Suggestions as each auction finishes.
        </p>
      )}
      <div className="scroll"><table>
        <thead><tr><th>Source</th><th>Status</th><th>Lots / birds</th><th>Last run</th><th>Last success</th><th>Notes</th></tr></thead>
        <tbody>{data?.map((s) => (
          <tr key={s.key}>
            <td><a href={s.base_url} target="_blank" rel="noopener noreferrer">{s.name}</a>{!s.verified && <div className="small muted">not yet verified on live pages</div>}</td>
            <td><span className={`badge status-${s.status.replace(/ /g, "-")}`}>{s.status}</span>
              {s.key !== "benzing" && progressText(s.progress) && <div className="small">⏳ {progressText(s.progress)}</div>}
              {s.key === "benzing" && ingestText(s.progress) && <div className="small">⏳ {ingestText(s.progress)}</div>}</td>
            <td>{s.lot_count}</td><td>{when(s.last_run)}</td><td>{when(s.last_success)}</td>
            <td className="small">{s.message}
              {/blocked|refused|challenge/i.test(s.message || "") && (
                <div className="muted">The site turned the app away, so this source is paused (the app does not get round
                  bot protection). If the site opens normally in your browser, it blocks automated readers: ask the site
                  to allow “OLRScout” in its firewall, and put your email in OLR_SCOUT_CONTACT in the .env file so they
                  can see who it is. It is retried at the next full refresh.</div>
              )}
              {s.detail && Object.keys(s.detail).length > 0 && <details><summary>detail</summary><pre className="ocr">{JSON.stringify(s.detail, null, 2)}</pre></details>}</td>
            <td><button className="btn ghost" onClick={() => run("/sources/refresh", { only: [s.key] }, `Refresh ${s.key}`)} disabled={s.key === "benzing"}>Run</button></td>
          </tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}
