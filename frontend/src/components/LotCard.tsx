import { Link } from "react-router-dom";
import { api, LotCard as Lot } from "../lib/api";
import { countdown, pct, useNow, zar } from "../lib/format";

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

export function Countdown({ iso }: { iso: string | null }) {
  const now = useNow();
  const c = countdown(iso, now);
  return <span className={c.urgent ? "countdown urgent" : "countdown"}>{c.text}</span>;
}

export default function LotCard({ lot, onWatch }: { lot: Lot; onWatch?: () => void }) {
  const p = lot.performance as Record<string, unknown> | null;
  const watch = async () => {
    await api.post(`/lots/${lot.id}/watch`, {});
    onWatch?.();
  };
  return (
    <article className={`card ${lot.claim_mismatch ? "mismatch" : ""}`}>
      {lot.claim_mismatch && <div className="redflag">⚠ Claim mismatch: the text says ace/winner but the verified result is mid-field.</div>}
      <div className="card-top">
        {lot.image_url ? <img src={lot.image_url} alt="" loading="lazy" /> : <div className="noimg">no photo</div>}
        <div className="card-main">
          <div className="row wrap">
            <TierBadge tier={lot.tier} />
            {lot.score !== null && <span className="score">{lot.rank_score?.toFixed(0)}<small>/100</small></span>}
            <span className={`badge match-${lot.match_confidence}`}>match: {lot.match_confidence}{lot.ring_low_confidence ? " (low)" : ""}</span>
            {lot.own_lot && <span className="badge own">your loft</span>}
            {lot.you_lead && <span className="badge lead">you lead</span>}
          </div>
          <Link to={`/lot/${lot.id}`} className="title">{lot.ring || lot.title}</Link>
          <div className="muted">
            {lot.auction_name} · lot {lot.lot_no ?? "?"} · {lot.seller || "seller ?"} · {lot.source}
          </div>
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
      <div className="facts">
        {lot.tier === "A" && p && (
          <span>
            long {pct(p.long_score)} · all {pct(p.all_score)}{p.is_ace ? " · ACE" : ""}
            {p.final_position ? ` · final #${p.final_position}` : ""} · family {pct(p.family_rate)}
            {p.small_family_sample ? " (small sample)" : ""}
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
      </div>
    </article>
  );
}
