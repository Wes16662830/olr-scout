"""Pedigree parsing (Tier B): pull sire/dam/grandparent claims out of seller text.

Seller text is marketing until a claimed ancestor's ring is found in OLR results
with a real position. Nothing here scores an unverified claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..rings import find_rings, normalise

ACE_WORDS = re.compile(
    r"\b(ace|winner|won|1st|first\s+prize|champion|olr\s+winner|top\s*\d{1,2}\b|best\s+bird|super\s+breeder|golden)",
    re.I,
)

# (pattern, relation). Order matters: grandparent words before parent words.
RELATION_WORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:grand\s*son|grand\s*daughter|g\.?\s*son|g\.?\s*daughter|grandchild|kleinseun|kleindogter)\s+of\b", re.I), "grandparent"),
    (re.compile(r"\b(?:sire|father|vader|vater|vader\s*:)\b|\bs\s*:", re.I), "sire"),
    (re.compile(r"\b(?:dam|mother|moeder|mutter)\b|\bd\s*:", re.I), "dam"),
    (re.compile(r"\b(?:son|daughter|seun|dogter|child|kind|direct\s+from|out\s+of|uit)\s+(?:of|van)?\b", re.I), "parent"),
    (re.compile(r"\b(?:grand\s*sire|grand\s*father|grootvader)\b", re.I), "grandparent"),
    (re.compile(r"\b(?:grand\s*dam|grand\s*mother|grootmoeder)\b", re.I), "grandparent"),
]


@dataclass
class Claim:
    relation: str  # sire | dam | parent | grandparent | ancestor
    ring_raw: str | None
    ring_norm: str | None
    name: str | None
    text: str
    claims_ace: bool
    origin: str = "text"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _relation_before(sentence: str, pos: int) -> str:
    best, best_at = "ancestor", -1
    prefix = sentence[:pos]
    for pat, rel in RELATION_WORDS:
        for m in pat.finditer(prefix):
            if m.end() > best_at:
                best, best_at = rel, m.end()
    return best


_NAME_AFTER = re.compile(r"""^\s*[\(\-–,:]?\s*["'“‘]([^"'”’]{2,40})["'”’]""")


def extract_claims(*texts: str | None, origin: str = "text", own_ring: str | None = None) -> list[Claim]:
    own = normalise(own_ring) if own_ring else None
    claims: list[Claim] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for sent in _sentences(str(text)):
            up = sent.upper()
            located = []
            for ring in find_rings(sent):
                pos = up.find(ring.raw)
                located.append((pos if pos >= 0 else 0, ring))
            located.sort(key=lambda x: x[0])
            for i, (pos, ring) in enumerate(located):
                n = normalise(ring.raw)
                if not n or n == own or n in seen:
                    continue
                seen.add(n)
                rel = _relation_before(sent, pos)
                # "Dam: X daughter of Y" → Y is a grandparent of the lot bird.
                if rel == "parent" and i > 0 and _relation_before(sent, located[i - 1][0]) in ("sire", "dam"):
                    rel = "grandparent"
                prev_end = located[i - 1][0] + len(located[i - 1][1].raw) if i > 0 else 0
                next_start = located[i + 1][0] if i + 1 < len(located) else len(sent)
                segment = sent[prev_end:next_start]
                after = sent[pos + len(ring.raw):next_start]
                nm = _NAME_AFTER.match(after)
                claims.append(Claim(rel, ring.raw, n, nm.group(1).strip() if nm else None, sent[:400],
                                    bool(ACE_WORDS.search(segment)), origin))
    return claims


def generation_weight(relation: str) -> float:
    return {"sire": 1.0, "dam": 1.0, "parent": 1.0, "grandparent": 0.5}.get(relation, 0.35)


def is_mismatch(claims_ace: bool, bird_is_ace: bool, best_race_pct: float | None, threshold: float) -> bool:
    """'ace/winner' claimed but the matched bird finished mid-field."""
    if not claims_ace:
        return False
    if bird_is_ace:
        return False
    return best_race_pct is None or best_race_pct > threshold
