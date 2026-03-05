from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Tuple
import pandas as pd
import random

COLS = {
    # Variant-level columns (in your Attraction Groups tab)
    "variant_id": "id",
    "variant_title": "title",
    "variant_hot": "hot_seller_score",

    # Group columns (also present in each variant row)
    "group_id": "attraction_group_id",
    "group_title": "attraction_group_title",
    "must_do": "Cairns_must_do",
    "primary": "primary_sub_category",
    "secondary": "secondary_sub_category",
    "tertiary": "tertiary_sub_category",
    "fatigue": "fatigue_level",
    "non_swimmer": "for_non_swimmers?",
    "pensioner": "pensioner_friendly?",
    "kid": "kid_friendly?",
    "infant": "infant_friendly?",
    "duration": "duration in hours",

    # Fillers tab
    "filler_title": "Attraction",
    "filler_region": "Base Region",
    "filler_min_dur": "Min. Duration",
}

def _truthy(x) -> bool:
    if pd.isna(x): return False
    if isinstance(x, (int, float)): return x != 0
    s = str(x).strip().lower()
    return s in ("true", "yes", "y", "1", "t")

def _selected_half_day(ctx: Context) -> bool:
    return any(str(x).strip().lower() == "half day tours" for x in ctx.selected_subcats)

def _selected_full_day(ctx: Context) -> bool:
    return any(str(x).strip().lower() == "full day tours" for x in ctx.selected_subcats)

@dataclass
class Context:
    start_date: date
    end_date: date
    adults: int
    children: int
    infants: int
    pensioners: int
    can_swim: bool
    selected_must_dos: List[str]
    selected_subcats: List[str]

def trip_days(ctx: Context) -> int:
    return (ctx.end_date - ctx.start_date).days + 1

def filter_variants(variants: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    v = variants.copy()

    # Traveller hard filters (applied at row level)
    if ctx.infants > 0 and COLS["infant"] in v.columns:
        v = v[v[COLS["infant"]].apply(_truthy)]
    if ctx.children > 0 and COLS["kid"] in v.columns:
        v = v[v[COLS["kid"]].apply(_truthy)]
    if ctx.pensioners > 0 and COLS["pensioner"] in v.columns:
        v = v[v[COLS["pensioner"]].apply(_truthy)]
    if ctx.can_swim is False and COLS["non_swimmer"] in v.columns:
        v = v[v[COLS["non_swimmer"]].apply(_truthy)]

    # DEBUG HERE (after traveller filters)
    scuba_rows = v[
        v[COLS["group_id"]].astype(str).str.strip() == "AG_Scuba_Diving_01"
    ]

    print("----- DEBUG SCUBA -----")
    print("can_swim:", ctx.can_swim)
    print("infants:", ctx.infants,
          "children:", ctx.children,
          "pensioners:", ctx.pensioners)
    print("Scuba rows remaining after traveller filters:", len(scuba_rows))
    print(scuba_rows[[
        COLS["variant_id"],
        COLS["variant_title"],
        COLS["non_swimmer"],
        COLS["kid"],
        COLS["infant"],
        COLS["pensioner"],
    ]])
    print("-----------------------")

    must_do_sel = set([str(x).strip() for x in ctx.selected_must_dos if str(x).strip()])

    must_do_sel = set([str(x).strip() for x in ctx.selected_must_dos if str(x).strip()])
    subcat_sel = set(str(x).strip().lower() for x in ctx.selected_subcats if str(x).strip())
    ALIASES = {
        "rafting": "whitewater rafting", 
        "market visit": "market visit",
        "museum visit": "museum visit",
        "hot air balloon": "hot air balloon flights",  
    }
        # Expand selection with aliases
    expanded = set()
    for s in subcat_sel:
        expanded.add(s)
        if s in ALIASES:
            expanded.add(ALIASES[s])
    subcat_sel = expanded
    print("subcat_sel:", subcat_sel)
    scuba_group = v[v[COLS["group_id"]].astype(str).str.strip() == "AG_Scuba_Diving_01"]
    print("Scuba subcats in data:")
    print(scuba_group[[COLS["primary"], COLS["secondary"], COLS["tertiary"]]])
    

    def matches(row) -> bool:
        md = str(row.get(COLS["must_do"], "")).strip()
        if md and md in must_do_sel:
            return True

        subcats = {
            str(row.get(COLS["primary"], "")).strip().lower(),
            str(row.get(COLS["secondary"], "")).strip().lower(),
            str(row.get(COLS["tertiary"], "")).strip().lower(),
        }
        subcats.discard("")
        return len(subcats.intersection(subcat_sel)) > 0
 
    # Keep only rows matching user selections
    v = v[v.apply(matches, axis=1)]
    print("Rows after subcategory matching:", len(v))
    print("Unique group_ids after matching:", v[COLS["group_id"]].unique())

    # Hard filter: Half Day vs Full Day preference
    half_selected = any(str(x).strip().lower() == "half day tours" for x in ctx.selected_subcats)
    full_selected = any(str(x).strip().lower() == "full day tours" for x in ctx.selected_subcats)

    # Only enforce if user picked exactly one of them
    if half_selected and not full_selected:
        v = v[~v[COLS["group_id"]].astype(str).str.contains("full", case=False, na=False)]

    if full_selected and not half_selected:
        v = v[~v[COLS["group_id"]].astype(str).str.contains("half", case=False, na=False)]

    return v

def build_groups_from_variants(filtered_variants: pd.DataFrame) -> pd.DataFrame:
    """
    Convert variant rows into a group table by:
    - grouping by attraction_group_id
    - taking the max hot_seller_score row as representative (for ranking/display)
    """
    v = filtered_variants.copy()
    v[COLS["variant_hot"]] = pd.to_numeric(v.get(COLS["variant_hot"], 0), errors="coerce").fillna(0)

    # Pick representative variant per group = highest hot score
    idx = v.groupby(COLS["group_id"])[COLS["variant_hot"]].idxmax()
    groups = v.loc[idx].copy()

    return groups

def _score_group(row: pd.Series, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    score = 0.0
    why = {"tags": []}

    must_do_sel = set([str(x).strip() for x in ctx.selected_must_dos if str(x).strip()])
    subcat_sel = set([str(x).strip() for x in ctx.selected_subcats if str(x).strip()])

    md = str(row.get(COLS["must_do"], "")).strip()
    if md in must_do_sel:
        score += 50
        why["tags"].append("must_do_match")

    subcats = [
        str(row.get(COLS["primary"], "")).strip().lower(),
        str(row.get(COLS["secondary"], "")).strip().lower(),
        str(row.get(COLS["tertiary"], "")).strip().lower(),
    ]
    
    match_count = sum(1 for s in subcats if s and s in subcat_sel)
    if match_count:
        score += 40 * match_count
        why["tags"].append(f"subcat_matches:{match_count}")

    # Soft boosts for traveller fit
    if ctx.infants > 0 and _truthy(row.get(COLS["infant"], False)):
        score += 6
        why["tags"].append("infant_ok")
    if ctx.children > 0 and _truthy(row.get(COLS["kid"], False)):
        score += 4
        why["tags"].append("kid_ok")
    if ctx.pensioners > 0 and _truthy(row.get(COLS["pensioner"], False)):
        score += 4
        why["tags"].append("pensioner_ok")
    if ctx.can_swim is False and _truthy(row.get(COLS["non_swimmer"], False)):
        score += 6
        why["tags"].append("non_swimmer_ok")

    # Small nudge: good anchor durations
    try:
        dur = float(row.get(COLS["duration"], 0))
        if 6 <= dur <= 10:
            score += 3
            why["tags"].append("good_anchor_duration")
    except Exception:
        pass

    return score, why

def rank_groups(groups: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    g = groups.copy()
    scored = g.apply(lambda r: _score_group(r, ctx), axis=1, result_type="expand")
    g["score"] = scored[0]
    g["why"] = scored[1]
    return g.sort_values("score", ascending=False)

def build_itinerary(ranked_groups: pd.DataFrame, ctx: Context) -> List[Dict[str, Any]]:
    D = trip_days(ctx)
    day = ctx.start_date

    selected_must_dos = [str(x).strip() for x in ctx.selected_must_dos if str(x).strip()]
    must_do_remaining = set(selected_must_dos)

    # subcategory coverage targets (normalized)
    subcat_remaining = set(
        str(x).strip().lower()
        for x in ctx.selected_subcats
        if str(x).strip()
    )

    used_group_ids = set()
    used_must_dos = set()   
    last_day_high = False

    itinerary = []

    # Helper: does a row contain any remaining subcats?
    def row_matches_remaining_subcats(r) -> bool:
        row_subs = {
            str(r.get(COLS["primary"], "")).strip().lower(),
            str(r.get(COLS["secondary"], "")).strip().lower(),
            str(r.get(COLS["tertiary"], "")).strip().lower(),
        }
        row_subs.discard("")
        return len(row_subs.intersection(subcat_remaining)) > 0

    for i in range(D):
        days_left = D - i
        force_cover = (len(must_do_remaining) > 0) and (days_left >= len(must_do_remaining))

        candidates = ranked_groups.copy()

        # 1) Must-do coverage first 
        if force_cover and COLS["must_do"] in candidates.columns:
            candidates = candidates[candidates[COLS["must_do"]].astype(str).str.strip().isin(must_do_remaining)]

        # Avoid repeating same group_id
        candidates = candidates[~candidates[COLS["group_id"]].isin(used_group_ids)]

        # Avoid repeating same Must-Do (e.g., Fitzroy Full then Fitzroy Half)
        if COLS["must_do"] in candidates.columns:
            candidates = candidates[
                ~candidates[COLS["must_do"]].astype(str).str.strip().isin(used_must_dos)
            ]

        # 2) Once must-dos are done, force remaining subcats to appear
        force_subcats = (len(must_do_remaining) == 0) and (len(subcat_remaining) > 0)
        if force_subcats:
            subcat_candidates = candidates[candidates.apply(row_matches_remaining_subcats, axis=1)]
            # only switch if we actually have matches; otherwise keep current candidates
            if not subcat_candidates.empty:
                candidates = subcat_candidates

        # Fatigue guardrail: avoid high->high when possible
        if last_day_high and COLS["fatigue"] in candidates.columns:
            non_high = candidates[candidates[COLS["fatigue"]].astype(str).str.lower() != "high"]
            if not non_high.empty:
                candidates = non_high

        # Fallback if empty
        if candidates.empty:
            candidates = ranked_groups[~ranked_groups[COLS["group_id"]].isin(used_group_ids)]

            # apply Avoid repeating same group_id to fallback set
            if COLS["must_do"] in candidates.columns:
                candidates = candidates[
                    ~candidates[COLS["must_do"]].astype(str).str.strip().isin(used_must_dos)
                ]

            # ✅ also try subcat forcing on fallback set
            if (len(must_do_remaining) == 0) and (len(subcat_remaining) > 0):
                subcat_candidates = candidates[candidates.apply(row_matches_remaining_subcats, axis=1)]
                if not subcat_candidates.empty:
                    candidates = subcat_candidates

        if candidates.empty:
            itinerary.append({"date": day.isoformat(), "anchor_group": None})
            day = date.fromordinal(day.toordinal() + 1)
            continue

        pick = candidates.iloc[0]
        gid = pick[COLS["group_id"]]
        used_group_ids.add(gid)

        md = str(pick.get(COLS["must_do"], "")).strip()

        # Avoid repeating same group_id: mark this must-do as used so it cannot appear again
        if md:
            used_must_dos.add(md)

        if md in must_do_remaining:
            must_do_remaining.remove(md)

        # Remove satisfied subcats
        picked_subs = {
            str(pick.get(COLS["primary"], "")).strip().lower(),
            str(pick.get(COLS["secondary"], "")).strip().lower(),
            str(pick.get(COLS["tertiary"], "")).strip().lower(),
        }
        picked_subs.discard("")
        subcat_remaining -= picked_subs

        fatigue = str(pick.get(COLS["fatigue"], "")).strip().lower()
        last_day_high = (fatigue == "high")

        itinerary.append({
            "date": day.isoformat(),
            "anchor_group": {
                "group_id": gid,
                "title": str(pick.get(COLS["group_title"], "")),
                "must_do_group": md,
                "score": float(pick.get("score", 0)),
                "why": pick.get("why", {"tags": []}),
                "fatigue_level": str(pick.get(COLS["fatigue"], "")),
                "duration_hours": pick.get(COLS["duration"], None),
            }
        })

        day = date.fromordinal(day.toordinal() + 1)

    return itinerary

def attach_variants(itinerary: List[Dict[str, Any]], filtered_variants: pd.DataFrame, top_n: int = 5) -> List[Dict[str, Any]]:
    v = filtered_variants.copy()
    v[COLS["variant_hot"]] = pd.to_numeric(v.get(COLS["variant_hot"], 0), errors="coerce").fillna(0)

    for d in itinerary:
        ag = d.get("anchor_group")
        if not ag:
            d["variants"] = []
            continue

        gid = ag["group_id"]
        vv = v[v[COLS["group_id"]] == gid].sort_values(COLS["variant_hot"], ascending=False)

        d["variants"] = [
            {
                "product_id": r.get(COLS["variant_id"]),
                "title": r.get(COLS["variant_title"]),
                "adult_price": r.get("adult_price"),
                "child_price": r.get("child_price"),
                "image_url": r.get("image_url"),
                "duration_hours": r.get("duration in hours"),
                "hot_seller_score": float(r.get(COLS["variant_hot"], 0)),
            }
            for _, r in vv.head(top_n).iterrows()
        ]

    return itinerary

import random

def insert_fillers(itinerary, fillers, max_fillers=2):
    f = fillers.copy()

    # Evening recovery pool (hardcoded for now)
    EVENING_RECOVERY = [
        "Hemingway’s Brewery",
        "The Pier",
        "Cairns Night Markets",
    ]

    # Kuranda “must-push” bundle
    KURANDA_BUNDLE = [
        "Kuranda Rainforest Markets",
        "Koala Gardens",
        "Australian Butterfly Sanctuary",
        "Birdworld Kuranda",
    ]

    # Helper: pull duration safely
    def _dur_hours(day):
        try:
            ag = day.get("anchor_group") or {}
            return float(ag.get("duration_hours") or 0)
        except Exception:
            return 0.0

    for day in itinerary:
        ag = day.get("anchor_group")
        if not ag:
            day["fillers"] = []
            continue

        must_do = (ag.get("must_do_group") or "").strip()
        dur = _dur_hours(day)

        fillers_out = []

        # 1) Kuranda rule: always push the Kuranda free attractions bundle
        if must_do.lower() == "kuranda":
            day["fillers"] = ([{"title": x} for x in KURANDA_BUNDLE]
            )
            continue
        
        # 2) Long day rule: evening recovery suggestions
        if dur > 8:
            #fillers_out.append({"title": " Enjoy the rest of the evening with these recommended options"})
            for item in EVENING_RECOVERY:
                fillers_out.append({"title": item})
            day["fillers"] = fillers_out
            continue  # don’t add generic fillers after a long day

        # 3) Otherwise: normal fillers (current behaviour)
        picks = []
        for _, r in f.head(max_fillers).iterrows():
            picks.append({
                "title": r.get("Attraction"),
                "base_region": r.get("Base Region"),
                "min_duration": r.get("Min. Duration"),
            })

        day["fillers"] = fillers_out + picks

    return itinerary