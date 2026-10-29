import { Link } from "react-router-dom";
import { api, BirdSummary, Breeding, Lineage, LotCard as Lot } from "../lib/api";
import { countdown, pct, useNow, when, zar } from "../lib/format";

const TIER_TEXT: Record<string, string> = {
  A: "A · raced & verified",
  B: "B · verified parentage",
  C: "C · seller-claimed, unverified",
  D: "D · no usable data",
};

export function TierBadge({ tier }: { tier: Lot["tier"] }) {
  if (!tier) return null;
  return <span className={`badge tier-${tier}`}>{TIER_TEXT[tier]}</span>;
}

function LastBid({ lot }: { lot: Lot }) {
  const b = lot.last_bid;
  if (!b) return <div className="last-bid muted">No bids yet{lot.starting_bid ? ` · starts at ${zar(lot.starting_bid)}` : ""}</div>;
  return (
    <div className={`last-bid ${lot.you_lead ? "you" : ""}`}>
      Latest bid <b>{zar(b.amount)}</b>
      {b.bidder_shown
        ? <> by <b>{b.bidder || "unknown"}</b>{lot.you_lead ? " (you)" : ""}</>
        : <span className="muted"> · bidder not shown by the site</span>}
      {b.at && <span className="muted"> · {when(b.at)}</span>}
      {b.count !== null && b.count !== undefined && <span className="muted"> · {b.count} bid{b.count === 1 ? "" : "s"}</span>}
    </div>
  );
}

export function Countdown({ iso }: { iso: string | null }) {
  const now = useNow();
  const c = countdown(iso, now);
  return <span className={c.urgent ? "countdown urgent" : "countdown"}>{c.text}</span>;
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function chipClass(pct: number | null): string {
  if (pct === null) return "chip-miss";
  if (pct <= 0.1) return "chip-top";
  if (pct <= 0.33) return "chip-good";
  return "chip-mid";
}

function BirdBlock({ b, seller }: { b: BirdSummary; seller: string | null }) {
  return (
    <div className="bird">
      <div className="bird-line">
        {b.name && <b>“{b.name}” </b>}
        {[b.colour && `colour ${b.colour}`, b.sex].filter(Boolean).join(" · ")}
      </div>
      <div className="bird-line">
        <span className="label">Breeder (OLR entrant):</span> <b>{b.breeder || "not listed"}</b>
        {b.breeder_country ? ` (${b.breeder_country})` : ""}
        {seller && b.breeder && seller.toLowerCase() !== b.breeder.toLowerCase() && <span className="muted"> · seller: {seller}</span>}
      </div>
      <div className="races" title="Position / birds arrived. Underlined = one of the 5 longest races.">
        {b.races.map((r) => (
          <span key={r.label + r.name} className={`race ${chipClass(r.pct)} ${r.long ? "long" : ""}`}
            title={`${r.name}${r.km ? ` · ${r.km} km` : ""}${r.winner_speed ? ` · winner ${Math.round(r.winner_speed)} m/min (${r.speed_class ?? "?"} race)` : ""}${r.position ? ` · ${ordinal(r.position)} of ${r.arrived ?? "?"}` : " · did not arrive"}`}>
            <small>{r.label}</small> {r.position ? `${r.position}/${r.arrived ?? "?"}` : "–"}
          </span>
        ))}
      </div>
      <div className="small muted">
        {b.olr} {b.season}: arrived in {b.arrived_in} of {b.race_count}
        {b.best ? ` · best ${ordinal(b.best.position)} of ${b.best.arrived ?? "?"} (${b.best.label})` : ""}
        {b.long_score !== null ? ` · long races avg top ${pct(b.long_score)}` : ""}
        {b.final_position ? ` · final ${ordinal(b.final_position)}` : ""}
        {b.is_ace ? " · ACE" : ""}
      </div>
      <div className="small muted">
        {b.arrival_rate !== null && `Arrived ${Math.round(b.arrival_rate * 100)}% of races`}
        {b.lost_after && (b.lost_after === "never" ? " · never arrived" : ` · not seen after ${b.lost_after}`)}
        {b.hard_score !== null && ` · hardest races avg top ${pct(b.hard_score)}`}
        {b.speed_index !== null && ` · ${(b.speed_index * 100).toFixed(1)}% of winner's speed (long races)`}
      </div>
      <Conditions b={b} />
    </div>
  );
}

const SPEED_TEXT: Record<string, string> = { fast: "fast races (likely tailwind)", medium: "medium-speed races", slow: "slow, hard races (likely headwind)" };

function Conditions({ b }: { b: BirdSummary }) {
  const sp = b.best_speed, ds = b.best_distance;
  const fmt = (st: { races: number; avg: number }) => `avg top ${pct(st.avg)} over ${st.races}`;
  const bits: string[] = [];
  if (sp?.best) bits.push(`${SPEED_TEXT[sp.best] ?? sp.best} (${fmt(sp.by[sp.best])})`);
  if (ds?.best) bits.push(`${ds.best} (${fmt(ds.by[ds.best])})`);
  if (!bits.length) {
    if (!sp || !Object.keys(sp.by).length) return null;
    return <div className="small muted">Race conditions: no clear preference this season.</div>;
  }
  return (
    <div className="small conditions" title="Races are classed by the winner's speed against the season's other races (thirds) and by distance. One season gives only a few races per class, and weather is mostly luck — a hint, not a prediction for offspring.">
      <span className="label">Best this season in:</span> {bits.join(" · ")}
    </div>
  );
}

const CONF_TEXT: Record<string, string> = { low: "low confidence", medium: "medium confidence", high: "high confidence" };

function PedigreeClaims({ br }: { br: Breeding }) {
  const p = br.pedigree;
  if (!p) return null;
  const how = p.read_from === "ocr" ? "read from the pedigree image" : p.read_from === "pdf" ? "read from the pedigree PDF"
    : p.read_from === "text" ? "from the listing" : null;
  if (!p.ancestors_named) {
    if (p.read_error) return <div className="muted">Pedigree could not be read: {p.read_error}</div>;
    return p.has_pedigree ? <div className="muted">Pedigree not read yet (read automatically in the background).</div> : null;
  }
  return (
    <div className="muted">
      Pedigree claims ({how}): {p.ancestors_named} ancestor ring(s), {br.ancestors_verified ?? 0} found in OLR results
      {p.claimed_aces ? ` · ${p.claimed_aces} described as aces/winners — unverified, not scored` : ""}
    </div>
  );
}

function BreedingBlock({ br }: { br: Breeding }) {
  if (br.score === null || br.confidence === "none") {
    return (
      <div className="breeding small muted">
        Breeding: no offspring, sibling or verified-ancestor results yet — {br.pedigree?.ancestors_named
          ? "none of the named ancestors raced in the downloaded OLR seasons"
          : "no ancestor rings known"}. Own racing is not used as a breeding score.
        <PedigreeClaims br={br} />
      </div>
    );
  }
  const rec = (label: string, r?: { n: number; aces: number; mean_long: number } | null) =>
    r ? `${label}: ${r.n} raced, ${r.aces} ace${r.aces === 1 ? "" : "s"}, avg long top ${pct(r.mean_long)}` : null;
  const others = (br.ancestors_verified ?? 0) - (br.parents_verified ?? 0);
  const parts = [rec("Offspring", br.progeny), rec("Siblings", br.siblings),
    br.parents_verified ? `${br.parents_verified} parent(s) verified` : null,
    others > 0 ? `${others} other ancestor(s) verified` : null].filter(Boolean);
  return (
    <div className="breeding small">
      <span className="label">Breeding evidence</span> <span className={`badge conf-${br.confidence}`}>{CONF_TEXT[br.confidence]}</span>
      <div className="muted">{parts.join(" · ")}</div>
      <PedigreeClaims br={br} />
    </div>
  );
}

const STATUS_TEXT: Record<string, string> = { verified: "verified", mismatch: "claim mismatch", claimed: "seller-claimed" };

function Parents({ l }: { l: Lineage }) {
  return (
    <div className="parents">
      {l.parents.length === 0 && (
        <div className="small muted">Parents: not given in the listing{l.pedigree_url ? " — " : "."}
          {l.pedigree_url && <a href={l.pedigree_url} target="_blank" rel="noopener noreferrer">pedigree ↗</a>}</div>
      )}
      {l.parents.map((p, i) => (
        <div key={i} className="small">
          <span className="label">{p.relation === "parent" ? "Parent" : p.relation === "sire" ? "Sire" : "Dam"}:</span>{" "}
          <b>{p.ring || ""}</b>{p.name ? ` “${p.name}”` : ""}{" "}
          <span className={`badge st-${p.status}`}>{STATUS_TEXT[p.status] || p.status}</span>
          {p.record ? (
            <span className="muted"> {p.record.olr} {p.record.season}{p.record.long_score !== null ? `, long top ${pct(p.record.long_score)}` : ""}
              {p.record.is_ace ? ", ACE" : ""}{p.record.breeder ? `, ${p.record.breeder}` : ""}</span>
          ) : (
            p.ring && <span className="muted"> not in OLR results</span>
          )}
        </div>
      ))}
      {l.grandparents.total > 0 && (
        <div className="small muted">Grandparents named: {l.grandparents.total} ({l.grandparents.verified} verified in OLR results)</div>
      )}
      {l.parents.length > 0 && l.pedigree_url && (
        <div className="small"><a href={l.pedigree_url} target="_blank" rel="noopener noreferrer">Pedigree ↗</a></div>
      )}
    </div>
  );
}

function MyBid({ lot, onChange }: { lot: Lot; onChange?: () => void }) {
  const m = lot.my_bid;
  if (!m) return null;
  const probably = m.match === "masked" ? " (probably you — the site masks names)" : "";
  if (m.status === "leading") {
    return <div className="mybid leading">✔ You lead{m.your_max ? ` · ${zar(m.your_max)}` : ""}{probably}</div>;
  }
  if (m.status === "outbid") {
    return (
      <div className="mybid outbid">
        ✖ Outbid{m.your_max ? ` — your ${zar(m.your_max)}` : ""} · now {zar(m.top)}{m.top_bidder ? ` by ${m.top_bidder}` : ""}{probably}
      </div>
    );
  }
  return (
    <div className="mybid bid">
      You bid on this (marked by hand){" "}
      <button className="linklike" onClick={async () => { await api.post(`/lots/${lot.id}/mybid`, { on: false }); onChange?.(); }}>undo</button>
    </div>
  );
}

export default function LotCard({ lot, onWatch }: { lot: Lot; onWatch?: () => void }) {
  const p = lot.performance as Record<string, unknown> | null;
  const watch = async () => {
    await api.post(`/lots/${lot.id}/watch`, {});
    onWatch?.();
  };
  return (
    <article className={`card ${lot.claim_mismatch ? "mismatch" : ""} ${lot.my_bid ? `mine-${lot.my_bid.status}` : ""}`}>
      <MyBid lot={lot} onChange={onWatch} />
      {lot.claim_mismatch && <div className="redflag">⚠ Claim mismatch: the text says ace/winner but the verified result is mid-field.</div>}
      {lot.lot_no !== null && (
        <div className="lot-head">
          <span className="lotno">Lot {lot.lot_no}</span>
          <span className="lot-auction">{lot.auction_name}</span>
        </div>
      )}
      <div className="card-top">
        {lot.image_url ? <img src={lot.image_url} alt="" loading="lazy" /> : <div className="noimg">no photo</div>}
        <div className="card-main">
          <div className="row wrap">
            <TierBadge tier={lot.tier} />
            {lot.combined?.score != null && (
              <span className="score combined" title={`Combined: ${lot.combined.basis}`}>
                <small>Combined </small>{lot.combined.score.toFixed(0)}
              </span>
            )}
            {lot.score !== null && (
              <span className="score sub" title="Racing score: how this bird (or its verified ancestors) raced">
                <small>Racing </small>{lot.rank_score?.toFixed(0)}
              </span>
            )}
            <span className={`score sub breed ${lot.breeding_score == null ? "none" : ""}`}
              title="Breeding score: offspring, siblings and verified parents in OLR results">
              <small>Breeding </small>{lot.breeding_score == null ? "–" : lot.breeding_score.toFixed(0)}
            </span>
            <span className={`badge match-${lot.match_confidence}`}>match: {lot.match_confidence}{lot.ring_low_confidence ? " (low)" : ""}</span>
            {lot.own_lot && <span className="badge own">your loft</span>}
            {lot.you_lead && <span className="badge lead">you lead</span>}
          </div>
          <Link to={`/lot/${lot.id}`} className="title">{lot.ring || lot.title}{lot.bird_name && !lot.bird ? ` “${lot.bird_name}”` : ""}</Link>
          <div className="muted">
            {lot.lot_no === null ? `${lot.auction_name} · ` : ""}{lot.seller || "seller ?"} · {lot.source}
          </div>
          <LastBid lot={lot} />
          <div className="row wrap price-row">
            <span className={lot.over_max ? "price over" : lot.near_max ? "price near" : "price"}>
              {zar(lot.price)} <small>/ max {zar(lot.max)}</small>
            </span>
            <Countdown iso={lot.ends_at} />
            {lot.reserve_met === false && <span className="badge">reserve not met</span>}
            {lot.value_rank && <span className="badge">value #{lot.value_rank}</span>}
          </div>
        </div>
      </div>
      {lot.bird && <BirdBlock b={lot.bird} seller={lot.seller} />}
      {lot.lineage && <Parents l={lot.lineage} />}
      {lot.breeding && <BreedingBlock br={lot.breeding} />}
      <div className="facts">
        {lot.tier === "A" && p && (
          <span>
            family {String(p.family_key ?? "")}: {pct(p.family_rate)} aces{p.small_family_sample ? " (small sample)" : ""}
          </span>
        )}
        {lot.ancestors && (
          <span>ancestors: {lot.ancestors.verified} verified, {lot.ancestors.claimed} claimed{lot.ancestors.mismatch ? `, ${lot.ancestors.mismatch} mismatch` : ""}</span>
        )}
        <span>
          {lot.seller_stat
            ? `Seller: ${lot.seller_stat.sold_raced} sold birds raced, ${lot.seller_stat.sold_raced ? Math.round((lot.seller_stat.aces / lot.seller_stat.sold_raced) * 100) : 0}% aces`
            : "Seller: no OLR record yet"}
        </span>
        {lot.family_tags.length > 0 && (
          <span className="tags">{lot.family_tags.map((t) => <span key={t.name} className={`tag w-${t.weight}`}>{t.name}</span>)}</span>
        )}
      </div>
      <div className="row actions">
        <a className="btn" href={lot.url} target="_blank" rel="noopener noreferrer">Open lot ↗</a>
        <button className="btn ghost" onClick={watch}>Watch</button>
        {!lot.my_bid && (
          <button className="btn ghost" title="For sites that don't show bidder names: marks your bid and watches the lot"
            onClick={async () => {
              const v = window.prompt("Your bid on this lot (R) — leave empty if unsure:", lot.current_bid ? String(lot.current_bid) : "");
              if (v === null) return;
              await api.post(`/lots/${lot.id}/mybid`, { on: true, amount: v ? Number(v.replace(/[^0-9]/g, "")) || null : null });
              onWatch?.();
            }}>I bid on this</button>
        )}
      </div>
    </article>
  );
}
