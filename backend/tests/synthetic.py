"""SYNTHETIC OLR season used by the tests. Deterministic; not real data.

40 birds in 8 teams, 6 races (100–600 km, the last is the Final) plus one
training toss. Team 'Alpha Lofts' is made strong so family maths has signal.
"""

from __future__ import annotations

import random

TEAMS = ["Alpha Lofts I", "Alpha Lofts II", "Bravo & Charlie", "Charlie & Bravo (Single)",
         "Delta Lofts A", "Echo Lofts", "Foxtrot Lofts", "Golf Lofts"]
FLIGHTS = [
    {"id": 7001, "name": "Training 1", "distance": 50, "type": "training"},
    {"id": 7101, "name": "Race 1", "distance": 100},
    {"id": 7102, "name": "Race 2", "distance": 200},
    {"id": 7103, "name": "Race 3", "distance": 300},
    {"id": 7104, "name": "Race 4", "distance": 400},
    {"id": 7105, "name": "Race 5", "distance": 500},
    {"id": 7106, "name": "Final Race", "distance": 600},
]


def ring(i: int) -> str:
    return f"ZA-26-{100000 + i}"


def birds() -> list[dict]:
    out = []
    for i in range(40):
        out.append({"ring": ring(i), "team": TEAMS[i % len(TEAMS)]})
    return out


def results() -> dict[int, list[dict]]:
    """flight id → ordered result rows. Not every bird arrives in every race."""
    rng = random.Random(42)
    bs = birds()
    out = {}
    for f in FLIGHTS:
        if f.get("type") == "training":
            out[f["id"]] = []
            continue
        scored = []
        for i, b in enumerate(bs):
            strength = 0.0 if b["team"].startswith("Alpha") else 1.0
            # Bird 0 is the outright best; bird 5 is a weak bird (used for claim mismatch).
            if i == 0:
                strength = -2.0
            if i == 5:
                strength = 1.6
            arrive_p = 0.95 if f["distance"] <= 300 else 0.75
            if i == 5:
                arrive_p = 1.0
            if rng.random() > arrive_p and i not in (0, 5):
                continue
            scored.append((strength + rng.random(), b))
        scored.sort(key=lambda x: x[0])
        out[f["id"]] = [{"position": n + 1, "ringNumber": b["ring"], "teamName": b["team"], "speed": 1500 - n}
                        for n, (_, b) in enumerate(scored)]
    return out


def teams() -> list[dict]:
    by = {}
    for b in birds():
        by.setdefault(b["team"], []).append({"ringNumber": b["ring"]})
    return [{"name": t, "pigeons": p} for t, p in by.items()]
