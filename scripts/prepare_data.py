from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "support"
PUBLIC = ROOT / "public"

FORBIDDEN_PUBLIC_KEYS = {"name", "runnerid", "bibnumber", "bib", "fullname"}

BQ_ORDER = ["18-34","35-39","40-44","45-49","50-54","55-59","60-64","65-69","70-74","75-79","80+"]
BQ = {
    "M": {"18-34":10500,"35-39":10800,"40-44":11100,"45-49":11700,"50-54":12000,"55-59":12600,"60-64":13800,"65-69":14700,"70-74":15600,"75-79":16500,"80+":17400},
    "F": {"18-34":12300,"35-39":12600,"40-44":12900,"45-49":13500,"50-54":13800,"55-59":14400,"60-64":15600,"65-69":16500,"70-74":17400,"75-79":18300,"80+":19200},
    "X": {"18-34":12300,"35-39":12600,"40-44":12900,"45-49":13500,"50-54":13800,"55-59":14400,"60-64":15600,"65-69":16500,"70-74":17400,"75-79":18300,"80+":19200},
}

def age_to_bq_bracket(value):
    s = (value or "").strip().replace("–", "-").replace("—", "-").lower()
    if not s:
        return None
    if "80" in s and ("+" in s or "and" in s):
        return "80+"
    m = re.search(r"\d+", s)
    if not m:
        return None
    a = int(m.group())
    if a <= 34: return "18-34"
    if a <= 39: return "35-39"
    if a <= 44: return "40-44"
    if a <= 49: return "45-49"
    if a <= 54: return "50-54"
    if a <= 59: return "55-59"
    if a <= 64: return "60-64"
    if a <= 69: return "65-69"
    if a <= 74: return "70-74"
    if a <= 79: return "75-79"
    return "80+"

def bq_aggregates(finished_rows):
    by = {br: {"M":0,"F":0,"X":0} for br in BQ_ORDER}
    total = 0
    eligible = 0
    for r in finished_rows:
        t = parse_duration(r.get("TimeTotal"))
        if t is None:
            continue
        g = (r.get("Gender") or "").strip().upper()
        if g == "W": g = "F"
        if g not in BQ:
            continue
        br = age_to_bq_bracket(r.get("AgeGroup"))
        if not br:
            continue
        eligible += 1
        if t <= BQ[g][br]:
            total += 1
            by[br][g] += 1
    return {
        "count": total,
        "ratePct": pct(total, eligible),
        "eligibleSample": eligible,
        "byAgeGender": [{"age":br, **by[br]} for br in BQ_ORDER],
        "note": "Hypothetical Boston qualification using the site's 2026 standard table; no registration buffer applied."
    }


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_duration(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # tolerate "2:30:19 AM" from old exports by taking the H:M:S portion only
    m = re.search(r"(\d{1,2}):(\d{2}):(\d{2})", s)
    if not m:
        return None
    h, mi, sec = map(int, m.groups())
    return h * 3600 + mi * 60 + sec


def parse_clock(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            d = datetime.strptime(s, fmt)
            return d.hour * 3600 + d.minute * 60 + d.second
        except ValueError:
            pass
    return None


def fmt_duration(seconds):
    if seconds is None or not math.isfinite(seconds):
        return None
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def median(values):
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.median(vals) if vals else None


def pct(n, d):
    return round(100 * n / d, 2) if d else 0


def age_sort_key(label):
    m = re.search(r"\d+", label or "")
    return (int(m.group()) if m else 999, label or "")


def bin_times(values, width_sec, start=None, end=None):
    vals = [v for v in values if v is not None]
    if not vals:
        return []
    lo = (min(vals) // width_sec) * width_sec if start is None else start
    hi = math.ceil(max(vals) / width_sec) * width_sec if end is None else end
    counts = Counter(((v - lo) // width_sec) for v in vals if lo <= v <= hi)
    out = []
    bins = int((hi - lo) // width_sec) + 1
    for i in range(bins):
        a = lo + i * width_sec
        b = a + width_sec
        out.append({"start": a, "end": b, "count": counts.get(i, 0)})
    return out


def sanitize_country(code, country_map):
    code = (code or "").strip().upper()
    if not code:
        return ("Unknown", "Unknown", "UNK")
    meta = country_map.get(code, {})
    return (meta.get("Country", code), meta.get("Continent", "Unknown"), code)


def common_runner_aggregates(rows, country_map):
    statuses = Counter((r.get("RaceStatus") or "Unknown").strip() or "Unknown" for r in rows)
    finished_rows = [r for r in rows if (r.get("RaceStatus") or "").strip().lower() == "finished"]
    finish_seconds = [parse_duration(r.get("TimeTotal")) for r in finished_rows]
    finish_seconds = [x for x in finish_seconds if x is not None]
    starts = [parse_clock(r.get("StartTimeNet")) for r in rows]
    starts = [x for x in starts if x is not None]

    genders = Counter((r.get("Gender") or "Unknown").strip() or "Unknown" for r in rows)
    ages = Counter((r.get("AgeGroup") or "Unknown").strip() or "Unknown" for r in finished_rows)

    countries = Counter()
    regions = Counter()
    for r in finished_rows:
        cname, region, code = sanitize_country(r.get("CountryCode"), country_map)
        countries[(code, cname, region)] += 1
        regions[region] += 1

    country_rows = [
        {"code": code, "country": cname, "region": region, "count": count}
        for (code, cname, region), count in countries.most_common()
    ]

    bq = bq_aggregates(finished_rows)

    return {
        "overview": {
            "totalRunners": len(rows),
            "finishers": len(finished_rows),
            "finishRatePct": pct(len(finished_rows), len(rows)),
            "medianFinishSec": round(median(finish_seconds)) if finish_seconds else None,
            "medianFinish": fmt_duration(median(finish_seconds)),
            "under4Count": sum(x < 4 * 3600 for x in finish_seconds),
            "under4Pct": pct(sum(x < 4 * 3600 for x in finish_seconds), len(finish_seconds)),
            "fastestFinish": fmt_duration(min(finish_seconds)) if finish_seconds else None,
            "lastFinish": fmt_duration(max(finish_seconds)) if finish_seconds else None,
            "countriesRepresented": sum(1 for x in country_rows if x["code"] != "UNK"),
            "dsqCount": sum(v for k, v in statuses.items() if k.strip().lower() in {"dsq", "disqualified"}),
            "bqCount": bq["count"],
            "bqRatePct": bq["ratePct"],
        },
        "boston": bq,
        "status": [{"label": k, "count": v} for k, v in statuses.most_common()],
        "gender": [{"label": k, "count": v} for k, v in genders.most_common()],
        "ageGroups": [
            {"label": k, "count": v}
            for k, v in sorted(ages.items(), key=lambda kv: age_sort_key(kv[0]))
        ],
        "countries": country_rows,
        "regions": [{"label": k, "count": v} for k, v in regions.most_common()],
        "finishDistribution": bin_times(finish_seconds, 15 * 60),
        "startDistribution": bin_times(starts, 30 * 60),
    }


def build_2025(rows, split_rows, weather_rows, country_map):
    data = common_runner_aggregates(rows, country_map)
    by_id = {r.get("RunnerID"): r for r in rows if r.get("RunnerID")}

    # Segment definitions: cumulative timing columns and distance at each point.
    points = [
        ("5K", 5.0, "5kmTime"),
        ("10K", 10.0, "10kmTime"),
        ("15K", 15.0, "15kmTime"),
        ("20K", 20.0, "20kmTime"),
        ("Half", 21.0975, "HalbTime"),
        ("25K", 25.0, "25kmTime"),
        ("30K", 30.0, "30kmTime"),
        ("35K", 35.0, "35kmTime"),
        ("40K", 40.0, "40kmTime"),
        ("Finish", 42.195, None),
    ]

    segment_values = defaultdict(list)
    runner_metrics = []  # private in memory only; never serialized as individual records

    for s in split_rows:
        rid = s.get("RunnerID")
        rr = by_id.get(rid)
        if not rr or (rr.get("RaceStatus") or "").strip().lower() != "finished":
            continue
        finish = parse_duration(rr.get("TimeTotal"))
        half = parse_duration(rr.get("Halftime")) or parse_duration(s.get("HalbTime")) or parse_duration(s.get("Halftime"))
        if finish is None:
            continue

        cumulative = {}
        for label, dist, col in points:
            t = finish if label == "Finish" else parse_duration(s.get(col))
            cumulative[label] = t

        prev_label, prev_dist, prev_t = "Start", 0.0, 0
        for label, dist, col in points:
            t = cumulative[label]
            if t is not None and prev_t is not None and t > prev_t and dist > prev_dist:
                pace = (t - prev_t) / (dist - prev_dist)
                if 120 <= pace <= 1200:
                    segment_values[f"{prev_label}-{label}"].append(pace)
            prev_label, prev_dist, prev_t = label, dist, t

        split_pct = None
        split_class = None
        if half and finish > half:
            second = finish - half
            split_pct = (second / half - 1) * 100
            if split_pct < -2:
                split_class = "Negative >2%"
            elif split_pct <= 2:
                split_class = "Even ±2%"
            else:
                split_class = "Positive >2%"

        t10 = cumulative.get("10K")
        t20 = cumulative.get("20K")
        t30 = cumulative.get("30K")
        t40 = cumulative.get("40K")
        slowdown = None
        if all(x is not None for x in (t10, t20, t30, t40)):
            early = (t20 - t10) / 10
            late = (t40 - t30) / 10
            if early > 0 and late > 0:
                slowdown = (late / early - 1) * 100

        runner_metrics.append({
            "finish": finish,
            "splitClass": split_class,
            "splitPct": split_pct,
            "slowdown": slowdown,
        })

    segment_order = [
        "Start-5K", "5K-10K", "10K-15K", "15K-20K", "20K-Half",
        "Half-25K", "25K-30K", "30K-35K", "35K-40K", "40K-Finish"
    ]
    pacing = []
    for label in segment_order:
        vals = segment_values.get(label, [])
        med = median(vals)
        pacing.append({
            "segment": label,
            "medianPaceSecPerKm": round(med, 1) if med else None,
            "sample": len(vals),
        })

    split_counter = Counter(x["splitClass"] for x in runner_metrics if x["splitClass"])
    split_total = sum(split_counter.values())
    split_summary = [
        {"label": label, "count": split_counter.get(label, 0), "pct": pct(split_counter.get(label, 0), split_total)}
        for label in ("Negative >2%", "Even ±2%", "Positive >2%")
    ]

    slowdown_vals = [x["slowdown"] for x in runner_metrics if x["slowdown"] is not None and -80 < x["slowdown"] < 300]
    wall_bins = [
        ("Faster late", lambda x: x <= 0),
        ("0–5%", lambda x: 0 < x <= 5),
        ("5–10%", lambda x: 5 < x <= 10),
        ("10–20%", lambda x: 10 < x <= 20),
        ("20%+", lambda x: x > 20),
    ]
    wall_summary = []
    for label, fn in wall_bins:
        c = sum(fn(x) for x in slowdown_vals)
        wall_summary.append({"label": label, "count": c, "pct": pct(c, len(slowdown_vals))})

    finish_bands = [
        ("<3h", 0, 3 * 3600),
        ("3–3:30", 3 * 3600, int(3.5 * 3600)),
        ("3:30–4h", int(3.5 * 3600), 4 * 3600),
        ("4–4:30", 4 * 3600, int(4.5 * 3600)),
        ("4:30–5h", int(4.5 * 3600), 5 * 3600),
        ("5h+", 5 * 3600, 100 * 3600),
    ]
    slowdown_by_finish = []
    for label, lo, hi in finish_bands:
        vals = [x["slowdown"] for x in runner_metrics if lo <= x["finish"] < hi and x["slowdown"] is not None and -80 < x["slowdown"] < 300]
        slowdown_by_finish.append({
            "label": label,
            "medianSlowdownPct": round(median(vals), 1) if vals else None,
            "sample": len(vals),
        })

    # Largest increase between adjacent median segment paces, ignoring tiny Half segment.
    pace_clean = [x for x in pacing if x["medianPaceSecPerKm"] is not None and x["segment"] != "20K-Half"]
    wall_segment = None
    max_delta = -1e9
    for a, b in zip(pace_clean, pace_clean[1:]):
        delta = b["medianPaceSecPerKm"] - a["medianPaceSecPerKm"]
        if delta > max_delta:
            max_delta = delta
            wall_segment = b["segment"]

    data["pacing"] = pacing
    data["splitSummary"] = split_summary
    data["wallDistribution"] = wall_summary
    data["slowdownByFinishBand"] = slowdown_by_finish
    data["overview"].update({
        "medianLateSlowdownPct": round(median(slowdown_vals), 1) if slowdown_vals else None,
        "negativeSplitPct": next((x["pct"] for x in split_summary if x["label"].startswith("Negative")), 0),
        "evenSplitPct": next((x["pct"] for x in split_summary if x["label"].startswith("Even")), 0),
        "positiveSplitPct": next((x["pct"] for x in split_summary if x["label"].startswith("Positive")), 0),
        "largestSlowdownSegment": wall_segment,
    })

    # Weather is already aggregate / non-personal.
    weather = []
    for r in weather_rows:
        try:
            weather.append({
                "time": (r.get("HHmm") or "").strip(),
                "temperatureC": round(float(r.get("Temperature_C")), 1),
                "feelsLikeC": round(float(r.get("FeelsLike_C")), 1),
            })
        except (TypeError, ValueError):
            pass
    data["weather"] = weather
    data["meta"] = {
        "year": 2025,
        "raceDate": "2025-09-21",
        "privacy": "Aggregate-only public dataset; runner identifiers removed at build time.",
        "splitDefinition": "Negative/positive split categories use a ±2% even-split band.",
        "slowdownDefinition": "Late slowdown compares average pace from 30–40K with 10–20K.",
    }
    return data


def build_2024(rows, country_map):
    data = common_runner_aggregates(rows, country_map)
    data["meta"] = {
        "year": 2024,
        "raceDate": "2024-09-29",
        "privacy": "Aggregate-only public dataset; runner identifiers removed at build time.",
        "note": "The supplied project archive did not include the 2024 split file, so pacing/wall analysis is unavailable in this build.",
    }
    return data


def validate_privacy(obj, path="root"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(k).lower())
            if normalized in FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"Forbidden public key {k!r} at {path}")
            validate_privacy(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            validate_privacy(v, f"{path}[{i}]")


def write_json(year, data):
    validate_privacy(data)
    out_dir = PUBLIC / "data" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "dashboard.json"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size/1024:.1f} KiB)")


def main():
    map_rows = read_csv(SUPPORT / "MapCountryData.csv")
    country_map = {r.get("Code", "").strip().upper(): r for r in map_rows}

    rows25 = read_csv(SUPPORT / "BM_export_2025.csv")
    splits25 = read_csv(SUPPORT / "BM_export_splits_2025.csv")
    weather25 = read_csv(SUPPORT / "WeatherData.csv")
    write_json(2025, build_2025(rows25, splits25, weather25, country_map))

    rows24 = read_csv(SUPPORT / "BM_export_2024.csv")
    write_json(2024, build_2024(rows24, country_map))

    print("Privacy validation passed: public JSON contains no name, RunnerID, or bib-number fields.")


if __name__ == "__main__":
    main()
