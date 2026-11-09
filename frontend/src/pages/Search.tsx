import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import LotCard from "../components/LotCard";
import { LotCard as Lot } from "../lib/api";
import { useData } from "../lib/useData";

type Res = { lots: Lot[]; closed_count: number };

/** Results for the header search box: lot number, ring, or breeder / seller. Running
 *  auctions only, unless "include closed" is ticked. */
export default function Search() {
  const [params, setParams] = useSearchParams();
  const q = (params.get("q") || "").trim();
  const closed = params.get("closed") === "true";
  const nav = useNavigate();
  const { data, error, loading } = useData<Res>(q ? `/search?q=${encodeURIComponent(q)}${closed ? "&closed=true" : ""}` : null);
  const lots = data?.lots;
  // One lot only: open it straight away.
  useEffect(() => {
    if (lots && lots.length === 1 && !closed) nav(`/lot/${lots[0].id}`, { replace: true });
  }, [lots, closed, nav]);
  const toggle = (on: boolean) => setParams(on ? { q, closed: "true" } : { q });
  if (!q) return <section><h1>Search</h1><p>Type a lot number, a ring (any format, or just its number) or a breeder in the box at the top.</p></section>;
  return (
    <section>
      <h1>Search: “{q}”</h1>
      <label className="small"><input type="checkbox" checked={closed} onChange={(e) => toggle(e.target.checked)} />{" "}
        Include closed auctions{data && data.closed_count > 0 ? ` (${data.closed_count})` : ""}</label>
      {loading && !data && <p className="muted">Searching…</p>}
      {error && <p className="bad">{error}</p>}
      {lots && lots.length === 0 && (
        <p>No {closed ? "" : "running "}lots found{!closed && data!.closed_count > 0 ? ` — ${data!.closed_count} in closed auctions (tick the box above)` : ""}.
          Lot numbers match exactly; rings match on any part with 3+ digits; names need 3+ letters.</p>
      )}
      {lots && lots.length > 1 && <p className="muted">{lots.length} lots — closest match first (lot number, then ring, breeder, pedigree, listing text){closed ? "; running auctions before closed" : ""}.</p>}
      {lots?.map((l) => (
        <div key={l.id}>
          <div className="small muted">Found by: {(l.found_by || []).join(", ")}{l.status !== "live" ? ` · ${l.status}` : ""}</div>
          <LotCard lot={l} />
        </div>
      ))}
    </section>
  );
}
