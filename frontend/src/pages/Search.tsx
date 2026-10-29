import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import LotCard from "../components/LotCard";
import { LotCard as Lot } from "../lib/api";
import { useData } from "../lib/useData";

/** Results for the header search box: lot number, ring, or breeder / seller. */
export default function Search() {
  const [params] = useSearchParams();
  const q = (params.get("q") || "").trim();
  const nav = useNavigate();
  const { data, error, loading } = useData<Lot[]>(q ? `/search?q=${encodeURIComponent(q)}` : null);
  // One lot only: open it straight away.
  useEffect(() => {
    if (data && data.length === 1) nav(`/lot/${data[0].id}`, { replace: true });
  }, [data, nav]);
  if (!q) return <section><h1>Search</h1><p>Type a lot number, a ring (any format, or just its number) or a breeder in the box at the top.</p></section>;
  return (
    <section>
      <h1>Search: “{q}”</h1>
      {loading && !data && <p className="muted">Searching…</p>}
      {error && <p className="bad">{error}</p>}
      {data && data.length === 0 && (
        <p>No lots found. Lot numbers match exactly; rings match on any part with 3+ digits; names need 3+ letters.
          Closed lots are included, so a lot that was never downloaded can't be found.</p>
      )}
      {data && data.length > 1 && <p className="muted">{data.length} lots — closest match first (lot number, then ring, breeder, pedigree, listing text); live before closed within each.</p>}
      {data?.map((l) => (
        <div key={l.id}>
          <div className="small muted">Found by: {(l.found_by || []).join(", ")}{l.status !== "live" ? ` · ${l.status}` : ""}</div>
          <LotCard lot={l} />
        </div>
      ))}
    </section>
  );
}
