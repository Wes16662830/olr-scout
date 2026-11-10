"""Tier A scoring: a bird whose own ring matched OLR results.

Definitions (spec §6.1):
* percentile = position ÷ birds arrived (registered N if arrivals unknown);
  a race the bird is missing from counts as 1.0 (worst).
* long score = mean percentile over the season's 5 longest races.
* all-race score = mean over all races.
* ace = top 5% of registered birds, ranked by long score (then all-race score),
  so the field ace rate is 5% by construction.
* family ace rate (shrunk) = (aces + 0.05 × 20) ÷ (entries + 20).
* Bid Score = 50% long + 15% consistency + 10% final + 20% family + 5% siblings.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

FIELD_RATE = 0.05
PRIOR_N = 20
LONG_RACES = 5

# Racing score weights (editable in Settings). hard / reliability were added after the
# brief: placing in high-loss races and arriving at all. Speed is not scored: it mostly
# measures the day's wind and weather, and placing already compares birds on the same day.
DEFAULT_WEIGHTS = {"long": 40.0, "hard": 15.0, "consistency": 10.0, "final": 10.0, "family": 10.0, "sibling": 5.0,
                   "reliability": 5.0}
# In the long score (average placing over the longest races) the final counts up to this
# many times — only when it matches the bird's form in the other long races.
FINAL_WEIGHT = 3.0
# Gap between the final placing and the bird's form (both as a share of the starters):
# up to FINAL_MATCH the final is believed in full, from FINAL_OUTLIER on it is a one-off
# (a flash in the pan, or a bad day) and counts like any other race.
FINAL_MATCH = 0.15
FINAL_OUTLIER = 0.40


def final_trust(final_pct: float, form_pct: float | None) -> float:
    """1.0 when the final matches the bird's form, falling to 0.0 for a one-off."""
    if form_pct is None:
        return 1.0  # nothing else to judge it by
    gap = abs(final_pct - form_pct)
    if gap <= FINAL_MATCH:
        return 1.0
    if gap >= FINAL_OUTLIER:
        return 0.0
    return 1.0 - (gap - FINAL_MATCH) / (FINAL_OUTLIER - FINAL_MATCH)
# The bird's own results in the long and hard races, and its consistency across them,
# always carry at least this share of the racing score — whatever data is missing and
# whatever weights are set.
CORE = ("long", "hard", "consistency")
CORE_MIN_SHARE = 0.60
HARD_RACES = 3
# Shrunk family ace rate that earns the full family component (4× the field rate).
FAMILY_CEILING = 0.20


# ----------------------------------------------------------------- family grouping

_SUFFIX = re.compile(
    r"\s*[\-–]?\s*(?:\((?:single|i{1,3}|iv|v|[a-e]|\d)\)|\b(?:i{1,3}|iv|v|[a-e]|single|team\s*\d+|\d)\b\.?)\s*$",
    re.I,
)
_SPLIT = re.compile(r"\s*(?:&|\+|/|,|\band\b|\ben\b)\s*", re.I)


def family_key(team: str | None) -> str | None:
    """Group a team name into a family/partnership key.

    'Smith & Jones II' == 'Jones & Smith (Single)' == 'SMITH & JONES B' → 'jones & smith'.
    """
    if not team:
        return None
    t = " ".join(str(team).split())
    prev = None
    while prev != t:
        prev = t
        stripped = _SUFFIX.sub("", t).strip(" -–")
        # Never strip a partner's name: "A & B" keeps its B.
        if stripped and not re.search(r"(?:&|\+|/|,|\band|\ben)\s*$", stripped, re.I):
            t = stripped
    parts = [p.strip().lower() for p in _SPLIT.split(t) if p.strip()]
    parts = [re.sub(r"[^\w' ]", "", p).strip() for p in parts]
    parts = sorted({p for p in parts if p})
    return " & ".join(parts) if parts else None


def shrunk_rate(aces: int, entries: int, field_rate: float = FIELD_RATE, prior: int = PRIOR_N) -> float:
    return (aces + field_rate * prior) / (entries + prior)


# ----------------------------------------------------------------- season metrics

@dataclass
class FlightIn:
    id: int
    distance_km: float | None
    arrived: int | None = None
    is_training: bool = False
    is_final: bool = False
    name: str = ""
    basketed: int | None = None
    race_no: int | None = None


@dataclass
class BirdMetrics:
    ring_norm: str
    # flight id → race result 0..1 (0 best; 1.0 if missing): half placing among the starters,
    # half time behind the winner where speeds are known.
    percentiles: dict[int, float] = field(default_factory=dict)
    behind: dict[int, float] = field(default_factory=dict)  # flight id → minutes behind the winner
    positions: dict[int, int | None] = field(default_factory=dict)
    long_score: float = 1.0
    all_score: float = 1.0
    consistency: float = 0.0
    final_position: int | None = None
    final_percentile: float | None = None
    # Form = mean placing in the other long races; trust = how far the final is believed
    # (see final_trust); final_score_pct = the final as scored: blended toward form when
    # it was a one-off, so a flash in the pan earns no final bonus and a bad day no penalty.
    final_form: float | None = None
    final_trust: float | None = None
    final_score_pct: float | None = None
    is_ace: bool = False
    # Robustness measures
    hard_score: float | None = None  # mean percentile in the season's highest-loss races (1.0 if missing)
    arrival_rate: float = 0.0  # share of the season's races the bird arrived in
    lost_after: str | None = None  # "R6" if it arrived up to race 6 and never again; "never" if never arrived
    speed_index: float | None = None  # mean speed / winner's speed over long races it arrived in
    speed_pct: float | None = None  # rank of speed_index among the season's birds (0 = best)


def long_flight_ids(flights: list[FlightIn], n: int = LONG_RACES) -> list[int]:
    races = [f for f in flights if not f.is_training and f.distance_km]
    races.sort(key=lambda f: (f.distance_km or 0), reverse=True)
    return [f.id for f in races[:n]]


def field_size(arrived: int | None, basketed: int | None) -> int | None:
    """Birds a placing is measured against: those that started (basketed), else those home."""
    return max(arrived or 0, basketed or 0) or None


CONSISTENCY_CUT = 0.25  # "a good result": top quarter of the birds that started


def consistency(percentiles: dict[int, float], race_ids: set[int], cut: float = CONSISTENCY_CUT) -> float:
    """Share of the season's long and hard races in which the bird finished in the top
    quarter of the field (a missed race counts as not). All races if none are identified.
    (Top half was too easy: in AfrikaPro 2026 the best ~150 birds all scored 1.0.)"""
    ids = [i for i in race_ids if i in percentiles] or list(percentiles)
    if not ids:
        return 0.0
    return sum(1 for i in ids if percentiles[i] <= cut) / len(ids)


def hard_flight_ids(flights: list[FlightIn], n: int = HARD_RACES) -> list[int]:
    """The season's highest-loss races (1 - arrived/basketed). Needs basketing counts."""
    rated = [(1 - f.arrived / f.basketed, f.id) for f in flights
             if not f.is_training and f.basketed and f.arrived is not None and f.basketed >= f.arrived]
    if len(rated) < n:
        return []
    rated.sort(reverse=True)
    return [fid for _, fid in rated[:n]]


TIME_SHARE = 0.5  # a race result = half placing, half time behind the winner


def time_behind(distance_km: float | None, speed: float | None, winner_speed: float | None) -> float | None:
    """Minutes behind the winner, from speeds in metres per minute over the same distance."""
    if not distance_km or not speed or not winner_speed or speed <= 0:
        return None
    d = distance_km * 1000
    return max(0.0, d / speed - d / winner_speed)


def time_scores(distance_km: float | None, speeds: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    """Per bird: (minutes behind the winner, time score 0..1). The score scales minutes by
    the race's own spread: as far back as the middle bird home = 0.5, twice that or more
    = 1.0. So 250 birds landing within 3 minutes score almost alike, whatever their places."""
    win = max(speeds.values(), default=0)
    behind = {r: t for r, v in speeds.items() if (t := time_behind(distance_km, v, win)) is not None}
    if len(behind) < 3:
        return behind, {}
    vals = sorted(behind.values())
    median = vals[len(vals) // 2]
    if median <= 0:
        return behind, {}
    return behind, {r: min(1.0, 0.5 * t / median) for r, t in behind.items()}


def season_metrics(
    flights: list[FlightIn],
    results: dict[int, dict[str, int]],
    registered: set[str] | None = None,
    field_rate: float = FIELD_RATE,
    registered_count: int | None = None,
    speeds: dict[int, dict[str, float]] | None = None,
) -> dict[str, BirdMetrics]:
    """Compute per-bird metrics for one OLR season.

    ``results``: flight id → {ring_norm: position}. ``registered``: every bird in
    the season (from the teams endpoint); birds only seen in results are added.
    """
    races = [f for f in flights if not f.is_training]
    birds = set(registered or set())
    for fid, rows in results.items():
        birds.update(rows.keys())
    # Birds that never arrived anywhere have no ring in the results; the official
    # registered count (from the teams list) still sets the field size.
    n_reg = max(len(birds), registered_count or 0)
    long_ids = set(long_flight_ids(races))
    hard_ids = set(hard_flight_ids(races))
    finals = [f for f in races if f.is_final]
    final_ids = {f.id for f in finals}
    speeds = speeds or {}
    winner_speed = {fid: max(v.values()) for fid, v in speeds.items() if v}
    tscore: dict[int, dict[str, float]] = {}
    m_behind: dict[int, dict[str, float]] = {}
    for f in races:
        if speeds.get(f.id):
            m_behind[f.id], tscore[f.id] = time_scores(f.distance_km, speeds[f.id])
    out: dict[str, BirdMetrics] = {}
    for ring in birds:
        m = BirdMetrics(ring)
        for f in races:
            rows = results.get(f.id, {})
            pos = rows.get(ring)
            # Place among the birds that STARTED: in a hard race, coming home at all beats most
            # of the field, so last of 300 arrivals out of 1,000 basketed is not "last".
            arrived = f.arrived or (len(rows) if rows else None) or n_reg
            field = field_size(arrived, f.basketed)
            if pos is not None and field:
                pct = min(1.0, max(0.0, pos / field))
                ts = tscore.get(f.id, {}).get(ring)
                if ts is not None:  # half placing, half time behind the winner
                    pct = (1 - TIME_SHARE) * pct + TIME_SHARE * ts
            else:
                pct = 1.0
            m.percentiles[f.id] = pct
            if ring in m_behind.get(f.id, {}):
                m.behind[f.id] = m_behind[f.id][ring]
            m.positions[f.id] = pos
        if races:
            m.all_score = sum(m.percentiles.values()) / len(races)
            # Average placing over the longest races; the final counts up to FINAL_WEIGHT times,
            # as far as it matches the bird's form in the other long races.
            ids = (long_ids | final_ids) or set(m.percentiles)
            others = [m.percentiles[i] for i in ids if i not in final_ids]
            form = sum(others) / len(others) if others else None
            wts = {i: 1.0 for i in ids}
            for fid in final_ids & ids:
                trust = final_trust(m.percentiles[fid], form)
                wts[fid] = 1.0 + (FINAL_WEIGHT - 1.0) * trust
                m.final_form, m.final_trust = form, trust
                m.final_score_pct = trust * m.percentiles[fid] + (1 - trust) * (form if form is not None else 1.0)
            m.long_score = sum(m.percentiles[i] * w for i, w in wts.items()) / sum(wts.values())
            m.consistency = consistency(m.percentiles, long_ids | hard_ids)
        for f in finals:
            if m.positions.get(f.id) is not None:
                m.final_position = m.positions[f.id]
                m.final_percentile = m.percentiles[f.id]
        if races:
            arrived_in = [i for i, f in enumerate(races) if m.positions.get(f.id) is not None]
            m.arrival_rate = len(arrived_in) / len(races)
            if not arrived_in:
                m.lost_after = "never"
            elif arrived_in[-1] < len(races) - 1:
                last = races[arrived_in[-1]]
                m.lost_after = f"R{last.race_no}" if getattr(last, "race_no", None) else last.name or f"race {arrived_in[-1] + 1}"
        if hard_ids:
            m.hard_score = sum(m.percentiles[i] for i in hard_ids) / len(hard_ids)
        # Over every long race with speeds; a race it did not finish counts as 0, so missing
        # the hardest races can't make a bird look fast.
        timed = [i for i in long_ids if winner_speed.get(i, 0) > 0]
        if any(ring in speeds.get(i, {}) for i in timed):
            m.speed_index = sum(speeds[i].get(ring, 0.0) / winner_speed[i] for i in timed) / len(timed)
        out[ring] = m
    ranked = sorted((b for b in out.values() if b.speed_index is not None), key=lambda b: -b.speed_index)
    for i, b in enumerate(ranked):
        b.speed_pct = i / max(1, len(ranked) - 1) if len(ranked) > 1 else 0.0
    # Aces: top 5% of registered birds by long score.
    n_aces = max(1, math.ceil(field_rate * n_reg)) if n_reg else 0
    ranked = sorted(out.values(), key=lambda b: (b.long_score, b.all_score, b.ring_norm))
    for b in ranked[:n_aces]:
        if b.long_score < 1.0:
            b.is_ace = True
    return out


# ----------------------------------------------------------------- family stats

@dataclass
class FamilyAgg:
    key: str
    entries: int = 0
    aces: int = 0
    finalists: int = 0
    best_long: float | None = None

    @property
    def rate(self) -> float:
        return shrunk_rate(self.aces, self.entries)

    @property
    def small_sample(self) -> bool:
        return self.entries < 20


def aggregate_families(birds: list[tuple[str | None, BirdMetrics]]) -> dict[str, FamilyAgg]:
    """birds: [(family_key, metrics)]."""
    fams: dict[str, FamilyAgg] = {}
    for key, m in birds:
        if not key:
            continue
        f = fams.setdefault(key, FamilyAgg(key))
        f.entries += 1
        f.aces += int(m.is_ace)
        f.finalists += int(m.final_position is not None)
        if m.long_score < 1.0:
            f.best_long = m.long_score if f.best_long is None else min(f.best_long, m.long_score)
    return fams


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    if len(xs) < 3:
        return None
    return pearson(ranks(xs), ranks(ys))


def persistence(by_season: dict[int, dict[str, FamilyAgg]], min_entries: int = 5) -> list[dict]:
    """Year-to-year correlation of family ace rate between consecutive seasons."""
    years = sorted(by_season)
    out = []
    for a, b in zip(years, years[1:]):
        common = [k for k in by_season[a] if k in by_season[b]
                  and by_season[a][k].entries >= min_entries and by_season[b][k].entries >= min_entries]
        r = pearson([by_season[a][k].rate for k in common], [by_season[b][k].rate for k in common])
        out.append({"from": a, "to": b, "families": len(common), "r": r})
    return out


# ----------------------------------------------------------------- Bid Score

@dataclass
class BidScore:
    score: float
    components: dict[str, float]  # 0..1 each, only those with data
    weights_used: dict[str, float]
    missing: list[str]


def enforce_core_share(used: dict[str, float], minimum: float = CORE_MIN_SHARE) -> dict[str, float]:
    """Scale shares so the bird's own long/hard/consistency results hold at least
    ``minimum`` of the total (other components share the rest in proportion)."""
    core = sum(v for k, v in used.items() if k in CORE)
    other = sum(v for k, v in used.items() if k not in CORE)
    if core <= 0 or core >= minimum or other <= 0:
        return used
    return {k: (v * minimum / core if k in CORE else v * (1 - minimum) / other) for k, v in used.items()}


def bid_score(
    long_score: float,
    consistency: float,
    final_percentile: float | None,
    season_has_final: bool,
    family_rate: float | None,
    sibling_long_scores: list[float] | None,
    weights: dict[str, float] | None = None,
    family_ceiling: float = FAMILY_CEILING,
    hard_score: float | None = None,
    arrival_rate: float | None = None,
    speed_pct: float | None = None,  # not scored (see DEFAULT_WEIGHTS); kept for callers
) -> BidScore:
    """0–100. Components without data are left out and the remaining weights
    renormalised — nothing is filled in with a guess."""
    w = dict(DEFAULT_WEIGHTS)
    w.update(weights or {})
    comps: dict[str, float] = {"long": 1.0 - long_score, "consistency": consistency}
    missing = []
    if season_has_final:
        comps["final"] = (1.0 - final_percentile) if final_percentile is not None else 0.0
    else:
        missing.append("final")
    if family_rate is not None:
        comps["family"] = min(1.0, family_rate / family_ceiling)
    else:
        missing.append("family")
    if sibling_long_scores:
        comps["sibling"] = 1.0 - sum(sibling_long_scores) / len(sibling_long_scores)
    else:
        missing.append("sibling")
    for key, value in (("hard", None if hard_score is None else 1.0 - hard_score),
                       ("reliability", arrival_rate)):
        if value is None:
            missing.append(key)
        else:
            comps[key] = value
    total_w = sum(w.get(k, 0.0) for k in comps)
    used = {k: w.get(k, 0.0) / total_w for k in comps} if total_w else {}
    used = enforce_core_share(used)
    score = 100.0 * sum(comps[k] * used[k] for k in comps)
    return BidScore(round(score, 1), {k: round(v, 4) for k, v in comps.items()}, used, missing)
