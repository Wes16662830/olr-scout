"""User preferences: max bids, bloodline likes/dislikes, type filters, own birds."""

from __future__ import annotations

import copy
import re
import unicodedata

from sqlalchemy.orm import Session

from ..models import Preference
from .tier_a import DEFAULT_WEIGHTS, FAMILY_CEILING

PREF_WEIGHTS = {"love": 1.15, "like": 1.07, "neutral": 1.0, "avoid": 0.0}

SEED_FAMILIES = [
    {"name": "Janssen", "aliases": ["janssen", "jansen"]},
    {"name": "Thoné", "aliases": ["thone", "thoné", "thonė"]},
    {"name": "Kittel", "aliases": ["kittel"]},
    {"name": "Painters", "aliases": ["painters", "painter"]},
    {"name": "Proven Dream", "aliases": ["proven dream"]},
    {"name": "BAK 17", "aliases": ["bak 17", "bak17", "bak-17"]},
    {"name": "Freddy", "aliases": ["freddy"]},
    {"name": "Vandenabeele", "aliases": ["vandenabeele", "vd abeele"]},
    {"name": "Heremans-Ceusters", "aliases": ["heremans", "ceusters"]},
    {"name": "Van Loon", "aliases": ["van loon"]},
    {"name": "Leo Heremans", "aliases": ["leo heremans"]},
    {"name": "Gaby Vandenabeele", "aliases": ["gaby vandenabeele"]},
    {"name": "Bekaert", "aliases": ["bekaert"]},
    {"name": "Koopman", "aliases": ["koopman"]},
    {"name": "Hofkens", "aliases": ["hofkens"]},
]

DEFAULTS: dict = {
    "max_bid": 5000,
    "near_max_buffer": 500,
    "per_lot_max": {},  # lot id (str) → R
    "per_family_max": {},  # family name → R
    "families": [dict(f, weight="neutral") for f in SEED_FAMILIES],
    "distance_emphasis": "distance",  # distance | middle | balanced
    "sex": "any",  # any | cock | hen
    "year_min": None,
    "year_max": None,
    "min_races": 0,
    "ace_only": False,
    "include_tier_c": True,
    "own": {"team_names": ["Oudeluck, Baard & Spammer"], "usernames": ["GeForce RTX"], "exclude_own": False},
    "weights": dict(DEFAULT_WEIGHTS),
    "family_ceiling": FAMILY_CEILING,
    "mismatch_threshold": 0.20,
    "tier_c_cap": 60.0,
    # How many of each OLR's newest seasons (with races) to download. Older seasons
    # verify parents (Tier B), so raising this improves pedigree checks.
    "results_seasons": 2,
    # Suggestions order: "combined" (default), "racing" or "breeding".
    "rank_by": "combined",
    # Combined score: share of racing (50–100%); the rest is breeding, scaled by its confidence.
    "combined_racing_weight": 70,
    "breeding_weights": {"progeny": 40.0, "siblings": 25.0, "parents": 15.0, "breeder": 10.0, "own": 10.0},
}


def load(s: Session) -> dict:
    row = s.get(Preference, "user")
    prefs = copy.deepcopy(DEFAULTS)
    if row and isinstance(row.value, dict):
        for k, v in row.value.items():
            if isinstance(v, dict) and isinstance(prefs.get(k), dict) and k not in ("per_lot_max", "per_family_max"):
                prefs[k].update(v)
            else:
                prefs[k] = v
    return prefs


def save(s: Session, prefs: dict) -> dict:
    merged = load(s)
    merged.update(prefs)
    if merged["max_bid"] is None or int(merged["max_bid"]) < 0:
        raise ValueError("max_bid must be a positive amount in rand")
    from .tier_a import CORE, CORE_MIN_SHARE

    try:
        rw = float(merged.get("combined_racing_weight", 70))
    except (TypeError, ValueError):
        raise ValueError("Combined score: racing share must be a number from 50 to 100")
    if not 50 <= rw <= 100:
        raise ValueError("Combined score: racing share must be 50–100% — own racing always leads")

    w = merged.get("weights") or {}
    total = sum(float(v) for v in w.values()) or 1.0
    core = sum(float(w.get(k, 0)) for k in CORE)
    if core / total < CORE_MIN_SHARE:
        raise ValueError(
            f"Racing weights: long + hard + consistency must be at least {int(CORE_MIN_SHARE * 100)}% of the total "
            f"(now {round(100 * core / total)}%) — the bird's own long/hard-race results always lead.")
    row = s.get(Preference, "user") or Preference(key="user")
    row.value = merged
    s.add(row)
    s.flush()
    return merged


def fold(text: str | None) -> str:
    """Lowercase and strip accents: 'Thoné' → 'thone'."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def lot_text(lot) -> str:
    return " \n ".join(
        fold(x) for x in [lot.seller, lot.bloodline, lot.title, lot.description, lot.pedigree_text] if x
    )


def family_tags(lot, prefs: dict) -> list[dict]:
    text = lot_text(lot)
    tags = []
    for fam in prefs.get("families", []):
        names = [fam["name"], *fam.get("aliases", [])]
        for alias in names:
            a = fold(alias).strip()
            if a and re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", text):
                tags.append({"name": fam["name"], "weight": fam.get("weight", "neutral")})
                break
    return tags


def preference_multiplier(tags: list[dict]) -> float:
    """Avoid wins outright; otherwise the strongest liked family counts."""
    if not tags:
        return 1.0
    ws = [PREF_WEIGHTS.get(t["weight"], 1.0) for t in tags]
    if 0.0 in ws:
        return 0.0
    return max(ws)


def lot_max(lot, tags: list[dict], prefs: dict) -> int:
    """The tightest of: global max, a per-family max for any tagged family, a per-lot max."""
    limits = [int(prefs["max_bid"])]
    for t in tags:
        v = prefs.get("per_family_max", {}).get(t["name"])
        if v:
            limits.append(int(v))
    v = prefs.get("per_lot_max", {}).get(str(lot.id))
    if v:
        limits.append(int(v))
    return min(limits)


def is_own_lot(lot, prefs: dict) -> bool:
    own = prefs.get("own", {})
    hay = fold(" ".join(x for x in [lot.seller, lot.title, lot.auction_name] if x))
    return any(fold(n) and fold(n) in hay for n in own.get("team_names", []))


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", fold(text))


def bidder_match(shown: str | None, prefs: dict) -> str | None:
    """Is a bidder name, as the site shows it, one of your usernames?

    "exact": same name (case, accents and spaces ignored).
    "masked": the site hides letters (e.g. "G********X", "ge***tx") and the visible
    letters fit your name — probably you, but another bidder could fit too."""
    if not shown:
        return None
    names = [n for n in prefs.get("own", {}).get("usernames", []) if n]
    seen = _squash(shown)
    for n in names:
        if seen == _squash(n):
            return "exact"
    if "*" in seen:
        visible = seen.replace("*", "")
        if len(visible) < 2:
            return None  # "****" or "g***": too little to go on
        pattern = "^" + ".*".join(re.escape(p) for p in re.split(r"\*+", seen)) + "$"
        for n in names:
            if re.match(pattern, _squash(n)):
                return "masked"
    return None


def user_is_leading(lot, prefs: dict) -> bool:
    return bidder_match(lot.leading_bidder, prefs) is not None
