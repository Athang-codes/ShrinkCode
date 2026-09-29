#!/usr/bin/env python3
"""
generate_report.py — render one self-contained HTML before/after report from
the JSON artifacts the other shrinkcode scripts produce (v2, prompt #7).

Consumes any subset of:
    --loc-before/--loc-after          loc_report.py --save snapshots
                                      {"per_file": {...}, "totals": {code, ...}}
    --complexity-before/--complexity-after
                                      complexity_report.py --save snapshots
                                      {"per_function": [...], "totals": {...}}
    --duplicates/--duplicates-after   find_duplicates.py --json output
                                      {"exact_clusters": [...], "near_pairs": [...]}
    --batches                         batches.json manifest (see
                                      references/git-workflow.md): a list of
                                      {sha, category, tier, summary, verification}
    --plan                            plan.json (or the markdown compression
                                      plan) with an optional not-touched section

Missing inputs degrade to a note inside the report, never a crash — dropping
batches.json, for example, simply omits the batch table.

The output is genuinely self-contained: inline CSS, <details> elements for
collapsibility (no JavaScript at all), zero external references — it opens
straight from disk with no network access.

Usage:
    python3 generate_report.py --loc-before before_loc.json --loc-after after_loc.json \
        --complexity-before before_cx.json --complexity-after after_cx.json \
        --duplicates dups.json --batches batches.json --output report.html
"""
import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import display_path, utf8_stdout  # noqa: E402  (path setup above)

# Tier names/colors match the Mechanical/Structural/Semantic tier system
# (references/risk-classification.md) — same badges, same meaning, everywhere.
TIER_NAMES = {1: "Mechanical", 2: "Structural", 3: "Semantic"}
TIER_COLORS = {1: "#2e7d32", 2: "#b26a00", 3: "#6a1b9a"}

CSS = """
:root { --ink: #1c2733; --dim: #5b6b7c; --line: #d8dee6; --bg: #f6f8fa; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px; font: 15px/1.5 -apple-system, "Segoe UI", Roboto,
  Helvetica, Arial, sans-serif; color: var(--ink); background: var(--bg); }
main { max-width: 960px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 32px 0 12px; padding-bottom: 6px;
  border-bottom: 1px solid var(--line); }
.sub { color: var(--dim); font-size: 13px; margin-bottom: 24px; }
.cards { display: flex; flex-wrap: wrap; gap: 16px; }
.card { background: #fff; border: 1px solid var(--line); border-radius: 8px;
  padding: 16px 20px; min-width: 220px; flex: 1 1 220px; }
.card h3 { margin: 0 0 10px; font-size: 13px; text-transform: uppercase;
  letter-spacing: .06em; color: var(--dim); font-weight: 600; }
.card .now { font-size: 30px; font-weight: 700; }
.card .was { font-size: 13px; color: var(--dim); }
.delta { display: inline-block; margin-top: 8px; font-size: 13px; font-weight: 600;
  padding: 2px 8px; border-radius: 10px; }
.good { background: #e4f4e8; color: #1e6b38; }
.bad { background: #fbe7e7; color: #a02626; }
.neutral { background: #eef1f5; color: var(--dim); }
.bars { background: #fff; border: 1px solid var(--line); border-radius: 8px;
  padding: 18px 20px; }
.barmetric { margin-bottom: 18px; }
.barmetric:last-child { margin-bottom: 0; }
.barmetric .mtitle { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
svg text { font: 12px -apple-system, "Segoe UI", Roboto, sans-serif; }
.bar-label { fill: var(--dim); }
.bar-value { fill: var(--ink); font-weight: 600; }
table { width: 100%; border-collapse: collapse; background: #fff;
  border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line);
  vertical-align: top; font-size: 14px; }
th { background: #eef1f5; font-size: 12px; text-transform: uppercase;
  letter-spacing: .05em; color: var(--dim); }
tr:last-child td { border-bottom: none; }
code { font-family: ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace;
  font-size: 13px; background: #eef1f5; padding: 1px 5px; border-radius: 4px; }
.badge { display: inline-block; color: #fff; font-size: 12px; font-weight: 600;
  padding: 2px 9px; border-radius: 10px; white-space: nowrap; }
details { background: #fff; border: 1px solid var(--line); border-radius: 8px;
  padding: 12px 16px; margin-top: 12px; }
summary { cursor: pointer; font-weight: 600; font-size: 14px; }
ul.notouch { margin: 8px 0 0; padding-left: 20px; }
ul.notouch li { margin-bottom: 6px; }
.notes { background: #fff8e6; border: 1px solid #e8d9a8; border-radius: 8px;
  padding: 12px 16px; margin-top: 16px; font-size: 14px; }
.notes ul { margin: 6px 0 0; padding-left: 20px; }
.empty { color: var(--dim); font-style: italic; }
footer { margin: 36px 0 8px; color: var(--dim); font-size: 12px; }
"""


def esc(value):
    return html.escape(str(value), quote=True)


def load_json(path):
    # utf-8-sig: tolerate a BOM — Windows tools (and PowerShell's Out-File)
    # happily write one, and a stray BOM must not kill a whole report section.
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def load_loc(path):
    totals = load_json(path).get("totals", {})
    return {"code": totals.get("code"), "files": totals.get("files")}


def load_complexity(path):
    totals = load_json(path).get("totals", {})
    return {
        "avg": totals.get("avg_complexity"),
        "max": totals.get("max_complexity"),
        "total": totals.get("total_complexity"),
        "functions": totals.get("functions"),
    }


def load_duplicates(path):
    data = load_json(path)
    clusters = data.get("exact_clusters") or []
    near = data.get("near_pairs") or []
    locations = []
    for cluster in clusters:
        for loc in cluster:
            if isinstance(loc, dict):
                locations.append(f"{display_path(loc.get('path'))}:"
                                 f"{loc.get('line')}")
            elif isinstance(loc, (list, tuple)) and len(loc) == 2:
                locations.append(f"{display_path(loc[0])}:{loc[1]}")
    return {"clusters": len(clusters), "near_pairs": len(near), "locations": locations}


def load_batches(path):
    data = load_json(path)
    entries = data.get("batches") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("expected a JSON array of batch entries")
    return [b for b in entries if isinstance(b, dict)]


def load_not_touched(path):
    """Items deliberately left alone: plan.json's optional `notTouched` array,
    or the markdown plan's "Items NOT being touched, and why" bullet list."""
    if path.lower().endswith(".json"):
        data = load_json(path)
        items = data.get("notTouched") or data.get("not_touched") or []
        out = []
        for it in items:
            if isinstance(it, str):
                out.append((it, ""))
            elif isinstance(it, dict):
                out.append((it.get("item") or it.get("name") or "",
                            it.get("reason") or it.get("why") or ""))
        return out
    out = []
    in_section = False
    heading = re.compile(r"^##+\s+Items NOT being touched", re.IGNORECASE)
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if heading.match(line):
                in_section = True
                continue
            if in_section and line.startswith("##"):
                break
            if in_section and line.strip().startswith("- "):
                text = line.strip()[2:].strip()
                if " — " in text:
                    item, reason = text.split(" — ", 1)
                else:
                    item, reason = text, ""
                out.append((item, reason))
    return out


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------

def fmt(value, decimals=None):
    """Thousands-separated display; floats get 2 decimals only when they have
    them (avg 4.0 prints as "4", avg 4.5 as "4.5")."""
    if value is None:
        return "—"
    if isinstance(value, float):
        if decimals is None:
            decimals = 2 if abs(value - round(value)) > 1e-9 else 0
        return f"{value:,.{decimals}f}"
    return f"{int(value):,}"


def delta_badge(before, after, lower_is_better=True):
    """The delta chip under a card's headline number: green when it moved the
    right way, red when it regressed, gray when there is nothing to compare."""
    if before in (None, 0) or after is None:
        return '<span class="delta neutral">no baseline to compare</span>'
    delta = after - before
    pct = delta / before * 100.0
    improved = (delta < 0) if lower_is_better else (delta > 0)
    cls = "neutral" if delta == 0 else ("good" if improved else "bad")
    arrow = "▼" if delta < 0 else ("▲" if delta > 0 else "→")
    sign = "+" if delta > 0 else ""
    return (f'<span class="delta {cls}">{arrow} {sign}{fmt(delta)}'
            f' ({sign}{pct:.1f}%)</span>')


def card(title, now_text, was_text, badge_html):
    return (f'<div class="card"><h3>{esc(title)}</h3>'
            f'<div class="now">{esc(now_text)}</div>'
            f'<div class="was">{esc(was_text)}</div>'
            f'{badge_html}</div>')


def bar_svg(label, before, after, unit="", width=380):
    """Two rows (before/after), bar widths strictly proportional to the
    values — scaled against the larger of the two, so the ratio you see is
    the ratio that exists."""
    values = [v for v in (before, after) if v is not None]
    if not values:
        return ""
    maxv = max(values) or 1
    label_w = 64
    svg_w = label_w + width + 110
    rows = []
    y = 4
    for kind, v, color in (("Before", before, "#8ea6c1"), ("After", after, "#2f7d4f")):
        if v is None:
            continue
        w = max(2, int(round(float(v) / maxv * width)))
        rows.append(
            f'<text x="0" y="{y + 12}" class="bar-label">{kind}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w}" height="16" rx="3" '
            f'fill="{color}"></rect>'
            f'<text x="{label_w + w + 8}" y="{y + 12}" class="bar-value">'
            f'{esc(fmt(v))}{esc(unit)}</text>'
        )
        y += 24
    svg_h = max(28, y)
    return (f'<div class="barmetric"><div class="mtitle">{esc(label)}</div>'
            f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" '
            f'role="img" aria-label="{esc(label)} before {esc(fmt(before))}{esc(unit)} '
            f'after {esc(fmt(after))}{esc(unit)}">{"".join(rows)}</svg></div>')


def tier_badge(tier):
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        tier = None
    if tier in TIER_NAMES:
        name, color = TIER_NAMES[tier], TIER_COLORS[tier]
        return f'<span class="badge" style="background:{color}">T{tier} · {name}</span>'
    if tier is None:
        return '<span class="badge" style="background:#5b6b7c">—</span>'
    return f'<span class="badge" style="background:#5b6b7c">T{tier}</span>'


def batches_section(batches):
    """The batch table: category, tier badge, summary, verification, sha.
    The sha is plain text on purpose — the report must not assume a git host."""
    if not batches:
        return ('<h2>Batches</h2><p class="empty">No batch entries — nothing was '
                'checkpointed, or batches.json was not provided.</p>')
    rows = []
    for b in batches:
        rows.append(
            "<tr>"
            f"<td><code>{esc(b.get('category', '—'))}</code></td>"
            f"<td>{tier_badge(b.get('tier'))}</td>"
            f"<td>{esc(b.get('summary', ''))}</td>"
            f"<td>{esc(b.get('verification', ''))}</td>"
            f"<td><code>{esc(b.get('sha', '—'))}</code></td>"
            "</tr>"
        )
    return ('<h2>Batches</h2>'
            f'<table><thead><tr><th>Category</th><th>Tier</th><th>Summary</th>'
            f'<th>Verification</th><th>Commit</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def not_touched_section(items):
    if not items:
        return ""
    lis = []
    for item, reason in items:
        if reason:
            lis.append(f"<li><strong>{esc(item)}</strong> — {esc(reason)}</li>")
        else:
            lis.append(f"<li>{esc(item)}</li>")
    return ('<h2>Deliberately not touched</h2>'
            f'<ul class="notouch">{"".join(lis)}</ul>')


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Render a self-contained HTML before/after report from the JSON "
                    "artifacts the other shrinkcode scripts produce")
    ap.add_argument("--loc-before", help="loc_report.py --save snapshot (baseline)")
    ap.add_argument("--loc-after", help="loc_report.py --save snapshot (after the job)")
    ap.add_argument("--complexity-before",
                    help="complexity_report.py --save snapshot (baseline)")
    ap.add_argument("--complexity-after",
                    help="complexity_report.py --save snapshot (after)")
    ap.add_argument("--duplicates", help="find_duplicates.py --json output (baseline)")
    ap.add_argument("--duplicates-after",
                    help="find_duplicates.py --json output (after the job)")
    ap.add_argument("--batches", help="batches.json checkpoint manifest (optional)")
    ap.add_argument("--plan", help="plan.json or the markdown compression plan — powers "
                                   "the not-touched section (optional)")
    ap.add_argument("--output", default="shrinkcode_report.html",
                    help="output HTML path (default: shrinkcode_report.html)")
    ap.add_argument("--title", default="shrinkcode report", help="report title")
    args = ap.parse_args()

    if not any((args.loc_before, args.loc_after, args.complexity_before,
                args.complexity_after, args.duplicates, args.duplicates_after,
                args.batches, args.plan)):
        print("generate_report.py: nothing to report — pass at least one input "
              "(--loc-*, --complexity-*, --duplicates*, --batches, --plan)",
              file=sys.stderr)
        return 1

    notes = []

    def take(path, loader, label):
        """Optional by design: absent input -> section omitted quietly; a path
        that was given but can't be read -> an honest note in the report."""
        if not path:
            return None
        if not os.path.isfile(path):
            notes.append(f"{label}: file not found ({path}) — section skipped.")
            return None
        try:
            return loader(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            notes.append(f"{label}: could not read {path} ({exc}) — section skipped.")
            return None

    loc_before = take(args.loc_before, load_loc, "LOC baseline")
    loc_after = take(args.loc_after, load_loc, "LOC after")
    cx_before = take(args.complexity_before, load_complexity, "Complexity baseline")
    cx_after = take(args.complexity_after, load_complexity, "Complexity after")
    dup_before = take(args.duplicates, load_duplicates, "Duplicates baseline")
    dup_after = take(args.duplicates_after, load_duplicates, "Duplicates after")
    batches = take(args.batches, load_batches, "batches.json")
    not_touched = take(args.plan, load_not_touched, "Compression plan")

    def val(entry, key):
        return (entry or {}).get(key)

    # --- summary cards ---
    cards = []
    if loc_before or loc_after:
        if loc_after:
            now = fmt(val(loc_after, "code"))
            was = (f"before: {fmt(val(loc_before, 'code'))} code lines"
                   if loc_before else "no baseline snapshot")
        else:
            now = fmt(val(loc_before, "code"))
            was = "baseline snapshot only (no --loc-after)"
        cards.append(card("Lines of code", now, was,
                          delta_badge(val(loc_before, "code"), val(loc_after, "code"))))

    if cx_before or cx_after:
        if cx_after:
            now = fmt(val(cx_after, "avg"))
            was = (f"before: avg {fmt(val(cx_before, 'avg'))} across "
                   f"{fmt(val(cx_before, 'functions'))} functions"
                   if cx_before else "no baseline snapshot")
        else:
            now = fmt(val(cx_before, "avg"))
            was = "baseline snapshot only (no --complexity-after)"
        cards.append(card("Avg complexity", now, was,
                          delta_badge(val(cx_before, "avg"), val(cx_after, "avg"))))

    if dup_before or dup_after:
        before_clusters = val(dup_before, "clusters")
        after_clusters = val(dup_after, "clusters")
        if before_clusters is not None and after_clusters is not None:
            now = f"{max(0, before_clusters - after_clusters)} resolved"
            was = f"{fmt(before_clusters)} before → {fmt(after_clusters)} after"
            badge = delta_badge(before_clusters, after_clusters)
        elif dup_after:
            now, was = fmt(after_clusters), "after only (no --duplicates baseline)"
            badge = delta_badge(None, after_clusters)
        else:
            now, was = fmt(before_clusters), "baseline clusters (no --duplicates-after)"
            badge = delta_badge(None, before_clusters)
        cards.append(card("Duplication (exact clusters)", now, was, badge))

    # --- before/after bars: widths strictly proportional to the values ---
    bars = []
    if loc_before or loc_after:
        bars.append(bar_svg("Code lines", val(loc_before, "code"),
                            val(loc_after, "code")))
    if cx_before or cx_after:
        bars.append(bar_svg("Avg complexity", val(cx_before, "avg"),
                            val(cx_after, "avg")))
    if dup_before or dup_after:
        bars.append(bar_svg("Exact duplicate clusters",
                            val(dup_before, "clusters"),
                            val(dup_after, "clusters")))

    # baseline duplicate locations, as receipts (capped so a huge baseline
    # can't turn the report into a wall of paths)
    dup_details = ""
    locations = val(dup_before, "locations") or []
    if locations:
        shown = locations[:40]
        items = "".join(f"<li><code>{esc(loc)}</code></li>" for loc in shown)
        if len(locations) > len(shown):
            items += f"<li><em>… and {len(locations) - len(shown)} more</em></li>"
        dup_details = (f'<details><summary>Baseline duplicate locations '
                       f'({len(locations)})</summary>'
                       f'<ul class="notouch">{items}</ul></details>')

    batches_html = batches_section(batches) if batches is not None else ""
    not_touched_html = not_touched_section(not_touched)

    # --- notes / inputs footer ---
    notes_html = ""
    if notes:
        notes_html = ('<div class="notes"><strong>Notes</strong><ul>'
                      + "".join(f"<li>{esc(n)}</li>" for n in notes)
                      + "</ul></div>")

    consumed = [f"{label}: <code>{esc(path)}</code>" for label, path in (
        ("LOC baseline", args.loc_before), ("LOC after", args.loc_after),
        ("Complexity baseline", args.complexity_before),
        ("Complexity after", args.complexity_after),
        ("Duplicates baseline", args.duplicates),
        ("Duplicates after", args.duplicates_after),
        ("batches", args.batches), ("plan", args.plan)) if path]
    inputs_html = ('<details><summary>Report inputs</summary><ul class="notouch">'
                   + "".join(f"<li>{item}</li>" for item in consumed)
                   + "</ul></details>")

    bars_section = ""
    if any(bars):
        bars_section = (f'<section><h2>Before vs after</h2>'
                        f'<div class="bars">{"".join(bars)}</div></section>')

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>{{CSS}}</style>
</head>
<body>
<main>
<header>
<h1>{{TITLE}}</h1>
<p class="sub">Generated {{GENERATED}} — self-contained report: inline styles,
no scripts, no network access needed.</p>
</header>
<section>
<h2>Summary</h2>
<div class="cards">{{CARDS}}</div>
</section>
{{BARS_SECTION}}
{{BATCHES_SECTION}}
{{NOT_TOUCHED_SECTION}}
{{DUP_DETAILS}}
{{NOTES_SECTION}}
{{INPUTS}}
<footer>Produced by <code>scripts/generate_report.py</code> from the JSON
artifacts listed under Report inputs — every number is measured, none is
estimated.</footer>
</main>
</body>
</html>
"""
    doc = re.sub(
        r"\{\{[A-Z_]+\}\}",
        lambda m: {
            "{{TITLE}}": esc(args.title),
            "{{CSS}}": CSS,
            "{{GENERATED}}": esc(generated),
            "{{CARDS}}": "".join(cards),
            "{{BARS_SECTION}}": bars_section,
            "{{BATCHES_SECTION}}": batches_html,
            "{{NOT_TOUCHED_SECTION}}": not_touched_html,
            "{{DUP_DETAILS}}": dup_details,
            "{{NOTES_SECTION}}": notes_html,
            "{{INPUTS}}": inputs_html,
        }.get(m.group(0), m.group(0)),
        template,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"Wrote {args.output} ({len(doc):,} bytes) — open it directly in a browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
