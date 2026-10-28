"""Read the Nuxt payload embedded in a page's HTML.

Nuxt 3 writes ``<script type="application/json" id="__NUXT_DATA__">[...]`` in
the "devalue" flattened format: a JSON array where objects/arrays hold integer
indexes into the same array. ``unflatten`` rebuilds the original value.
"""

from __future__ import annotations

import json
import re

_NUXT_DATA = re.compile(r"""<script[^>]*id=["']__NUXT_DATA__["'][^>]*>(.*?)</script>""", re.S | re.I)
_NUXT_WINDOW = re.compile(r"""window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*</script>""", re.S)

_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef", "NuxtError"}


def unflatten(arr: list):
    cache: dict[int, object] = {}

    def hyd(i):
        if isinstance(i, int) and i < 0:
            return None  # -1 undefined, -2 null, etc.
        if i in cache:
            return cache[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _WRAPPERS:
                out = hyd(v[1]) if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] in ("Set",):
                out = [hyd(x) for x in v[1:]]
            elif v and isinstance(v[0], str) and v[0] in ("Map",):
                out = {str(hyd(v[j])): hyd(v[j + 1]) for j in range(1, len(v) - 1, 2)}
            elif v and isinstance(v[0], str) and v[0] in ("Date",):
                out = v[1]
            else:
                out = []
                cache[i] = out
                out.extend(hyd(x) for x in v)
                return out
        elif isinstance(v, dict):
            out = {}
            cache[i] = out
            for k, x in v.items():
                out[k] = hyd(x)
            return out
        else:
            out = v
        cache[i] = out
        return out

    return hyd(0)


def payload_from_html(html: str):
    m = _NUXT_DATA.search(html)
    if m:
        try:
            arr = json.loads(m.group(1))
            return unflatten(arr) if isinstance(arr, list) else arr
        except (json.JSONDecodeError, IndexError, RecursionError):
            pass
    m = _NUXT_WINDOW.search(html)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def find_seasons(payload) -> list[dict]:
    """Walk the payload for season-like objects: an id plus a year (or a year in the name)."""
    found: list[dict] = []
    seen: set[int] = set()

    def walk(node, under_season_key=False, depth=0):
        if depth > 40:
            return
        if isinstance(node, dict):
            keys = {k.lower() for k in node}
            sid = node.get("id") or node.get("seasonId")
            year = node.get("year") or node.get("seasonYear")
            name = str(node.get("name") or node.get("title") or "")
            if year is None:
                m = re.search(r"\b(20\d{2})\b", name)
                year = int(m.group(1)) if m and (under_season_key or "season" in name.lower()) else None
            if isinstance(sid, int) and year and (under_season_key or "season" in " ".join(keys)):
                if sid not in seen:
                    seen.add(sid)
                    found.append({"id": sid, "year": int(year), "name": name})
            for k, v in node.items():
                walk(v, under_season_key or "season" in k.lower(), depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, under_season_key, depth + 1)

    walk(payload)
    return sorted(found, key=lambda s: s["year"], reverse=True)
