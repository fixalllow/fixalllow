#!/usr/bin/env python3
"""Render a cohesive set of profile SVG cards from the GitHub GraphQL API.

Only aggregate numbers are published — never repository names or code.
Usage: GH_TOKEN=... python3 scripts/render.py
"""
import datetime as dt
import json
import math
import os
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("GH_USER", "fixalllow")
TOKEN = os.environ["GH_TOKEN"]
OUT = Path(__file__).resolve().parent.parent / "generated"
W = 860  # every card shares this width so they line up in the README

THEMES = {
    "dark": dict(bg="#0d1117", border="#21262d", text="#e6edf3", muted="#7d8590", subtle="#161b22",
                 line="#21262d", heat=["#161b22", "#0c3d4f", "#0b6a85", "#1b9fb3", "#4fe0b6"]),
    "light": dict(bg="#ffffff", border="#d0d7de", text="#1f2328", muted="#656d76", subtle="#f6f8fa",
                  line="#eaeef2", heat=["#ebedf0", "#b6e3ef", "#6cc5dd", "#1fa3bf", "#0f7e7a"]),
}
ACCENT = ("#00ADD8", "#41B883")
FONT = ('-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif')
MONO = '"SF Mono","JetBrains Mono","Fira Code",Menlo,Consolas,monospace'

STACK = [
    ("Languages", [("Go", "#00ADD8"), ("TypeScript", "#3178c6"), ("JavaScript", "#f1e05a"),
                   ("Python", "#3572A5"), ("Rust", "#dea584"), ("Dart", "#00B4AB")]),
    ("Backend", [("Gin", "#00ADD8"), ("NATS", "#27AAE1"), ("MongoDB", "#47A248"), ("SQLite", "#0F80CC"),
                 ("WebSocket", "#8b949e"), ("Protobuf", "#4285F4"), ("Node.js", "#5FA04E")]),
    ("Frontend", [("Vue 3", "#41B883"), ("Vite", "#646CFF"), ("Flutter", "#02569B")]),
    ("Infra", [("Linux", "#FCC624"), ("Nginx", "#009639"), ("GitHub Actions", "#2088FF"), ("Git", "#F05032")]),
]


# ---------------------------------------------------------------- data

def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if body.get("errors"):
        raise SystemExit(body["errors"])
    return body["data"]


CAL = "contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }"


def fetch():
    user = gql(f"""query($login:String!){{ user(login:$login){{ createdAt
        contributionsCollection {{ {CAL} }} }} }}""", login=USER)["user"]
    last_year = user["contributionsCollection"]["contributionCalendar"]

    # all-time daily counts, one calendar year per request
    days = {}
    start = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00")).year
    now = dt.datetime.now(dt.timezone.utc)
    for year in range(start, now.year + 1):
        cal = gql(f"""query($login:String!,$from:DateTime!,$to:DateTime!){{ user(login:$login){{
            contributionsCollection(from:$from,to:$to){{ {CAL} }} }} }}""",
                  login=USER, **{"from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"})
        for w in cal["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]

    langs, stars, repos, cursor = {}, 0, 0, None
    while True:
        page = gql("""query($login:String!,$cursor:String){ user(login:$login){
            repositories(ownerAffiliations:OWNER,isFork:false,first:100,after:$cursor){
              totalCount pageInfo{ hasNextPage endCursor }
              nodes{ stargazerCount languages(first:12,orderBy:{field:SIZE,direction:DESC}){
                edges{ size node{ name color } } } } } } }""", login=USER, cursor=cursor)
        r = page["user"]["repositories"]
        repos = r["totalCount"]
        for n in r["nodes"]:
            stars += n["stargazerCount"]
            for e in n["languages"]["edges"]:
                name = e["node"]["name"]
                size, color = langs.get(name, (0, e["node"]["color"] or "#8b949e"))
                langs[name] = (size + e["size"], color)
        if not r["pageInfo"]["hasNextPage"]:
            break
        cursor = r["pageInfo"]["endCursor"]

    return dict(last_year=last_year, days=days, langs=langs, stars=stars, repos=repos, since=start)


def streaks(days):
    dates = sorted(days)
    today = dt.date.today().isoformat()
    best, best_end, run = 0, None, 0
    for d in dates:
        if d > today:
            break
        run = run + 1 if days[d] else 0
        if run > best:
            best, best_end = run, d
    cur = 0
    for d in reversed([d for d in dates if d <= today]):
        if days[d]:
            cur += 1
        elif d != today:  # today not counted yet is fine
            break
    rng = ""
    if best_end:
        end = dt.date.fromisoformat(best_end)
        beg = end - dt.timedelta(days=best - 1)
        rng = f"{beg:%b %-d} – {end:%b %-d, %Y}"
    return cur, best, rng


# ---------------------------------------------------------------- svg helpers

def card(h, body, t, extra_css=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}">
<defs>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{ACCENT[0]}"/><stop offset="1" stop-color="{ACCENT[1]}"/>
  </linearGradient>
  <style>
    text{{font-family:{FONT}}} .mono{{font-family:{MONO}}}
    .label{{font-size:11px;font-weight:600;letter-spacing:.14em;fill:{t['muted']}}}
    .muted{{fill:{t['muted']}}} .fg{{fill:{t['text']}}}
    .in{{opacity:0;animation:in .5s ease-out forwards}}
    @keyframes in{{from{{opacity:0}}to{{opacity:1}}}}
    {extra_css}
    @media (prefers-reduced-motion:reduce){{.in,.draw{{opacity:1;animation:none;stroke-dashoffset:0}}}}
  </style>
</defs>
<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="14" fill="{t['bg']}" stroke="{t['border']}"/>
{body}
</svg>
"""


def header(title, right, t, y=40):
    return (f'<rect x="32" y="{y - 11}" width="3" height="14" rx="1.5" fill="url(#accent)"/>'
            f'<text x="44" y="{y}" class="label">{escape(title.upper())}</text>'
            f'<text x="{W - 32}" y="{y}" text-anchor="end" font-size="12" class="muted">{escape(right)}</text>')


def fmt(n):
    return f"{n:,}"


# ---------------------------------------------------------------- cards

def stats_card(data, t):
    cal = data["last_year"]
    cur, best, rng = streaks(data["days"])
    total = sum(data["days"].values())
    tiles = [
        ("CONTRIBUTIONS", fmt(cal["totalContributions"]), "last 12 months"),
        ("ALL-TIME", fmt(total), f"since {data['since']}"),
        ("CURRENT STREAK", f"{cur}", "days" if cur != 1 else "day"),
        ("LONGEST STREAK", f"{best}", rng or "days"),
    ]
    gap, pad = 14, 32
    tw = (W - 2 * pad - gap * 3) / 4
    body = [header("Overview", f"{data['repos']} repositories · {data['stars']} stars", t)]
    for i, (label, value, sub) in enumerate(tiles):
        x = pad + i * (tw + gap)
        body.append(f'''<g class="in" style="animation-delay:{.1 + i * .12:.2f}s">
  <rect x="{x:.1f}" y="62" width="{tw:.1f}" height="96" rx="10" fill="{t['subtle']}" stroke="{t['line']}"/>
  <text x="{x + 18:.1f}" y="86" class="label" font-size="10">{label}</text>
  <text x="{x + 16:.1f}" y="126" font-size="34" font-weight="700" fill="url(#accent)" letter-spacing="-.02em">{value}</text>
  <text x="{x + 18:.1f}" y="146" font-size="12" class="muted">{escape(sub)}</text>
</g>''')
    return card(186, "\n".join(body), t)


def heatmap_card(data, t):
    weeks = data["last_year"]["weeks"]
    counts = sorted(c for w in weeks for c in (d["contributionCount"] for d in w["contributionDays"]) if c)
    q = [counts[int(len(counts) * p)] for p in (.25, .5, .75)] if counts else [1, 2, 3]

    def level(c):
        if not c:
            return 0
        return 1 + sum(c > x for x in q)

    cell, gap = 11, 3.5
    step = cell + gap
    grid_w = len(weeks) * step - gap
    x0 = (W - grid_w) / 2
    y0 = 84
    body = [header("Contributions", f"{fmt(data['last_year']['totalContributions'])} in the last year", t)]

    last_month = None
    for i, w in enumerate(weeks):
        first = dt.date.fromisoformat(w["contributionDays"][0]["date"])
        if first.month != last_month and first.day <= 7 and i < len(weeks) - 2:
            body.append(f'<text x="{x0 + i * step:.1f}" y="{y0 - 10}" font-size="10" class="muted">{first:%b}</text>')
        last_month = first.month
        cells = []
        for d in w["contributionDays"]:
            wd = (dt.date.fromisoformat(d["date"]).weekday() + 1) % 7  # Sunday first
            cells.append(f'<rect x="{x0 + i * step:.1f}" y="{y0 + wd * step:.1f}" width="{cell}" height="{cell}" '
                         f'rx="2.5" fill="{t["heat"][level(d["contributionCount"])]}"/>')
        body.append(f'<g class="in" style="animation-delay:{i * .018:.3f}s">{"".join(cells)}</g>')

    for label, row in (("Mon", 1), ("Wed", 3), ("Fri", 5)):
        body.append(f'<text x="{x0 - 8:.1f}" y="{y0 + row * step + 9:.1f}" text-anchor="end" font-size="10" class="muted">{label}</text>')

    ly = y0 + 7 * step + 16
    lx = W - 32 - 5 * step - 30
    body.append(f'<text x="{lx - 8:.1f}" y="{ly + 9}" text-anchor="end" font-size="10" class="muted">Less</text>')
    for k in range(5):
        body.append(f'<rect x="{lx + k * step:.1f}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{t["heat"][k]}"/>')
    body.append(f'<text x="{lx + 5 * step + 4:.1f}" y="{ly + 9}" font-size="10" class="muted">More</text>')
    body.append(f'<text x="{x0:.1f}" y="{ly + 9}" font-size="10" class="muted">Includes private contributions · no repository details</text>')
    return card(int(ly + 36), "\n".join(body), t)


def smooth(points):
    """Catmull-Rom spline through points as an SVG cubic path."""
    d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def insights_card(data, t):
    h = 262
    body = [header("Activity", "weekly contributions · last 12 months", t)]

    # left: weekly area chart
    weekly = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in data["last_year"]["weeks"]]
    cx, cy, cw, ch = 62, 70, 450, 150
    peak = max(weekly) or 1
    top = max(10, math.ceil(peak / 10) * 10)
    for k in range(3):
        y = cy + ch * k / 2
        body.append(f'<line x1="{cx}" x2="{cx + cw}" y1="{y:.1f}" y2="{y:.1f}" stroke="{t["line"]}" stroke-dasharray="3 4"/>')
        body.append(f'<text x="{cx - 10}" y="{y + 3.5:.1f}" text-anchor="end" font-size="10" class="muted">{round(top * (1 - k / 2))}</text>')
    pts = [(cx + cw * i / (len(weekly) - 1), cy + ch - ch * v / top) for i, v in enumerate(weekly)]
    line = smooth(pts)
    area = f"{line} L{cx + cw},{cy + ch} L{cx},{cy + ch} Z"
    pi = weekly.index(peak)
    body.append(f'''<defs>
  <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{ACCENT[0]}" stop-opacity=".35"/><stop offset="1" stop-color="{ACCENT[1]}" stop-opacity="0"/>
  </linearGradient>
</defs>
<path d="{area}" fill="url(#fill)" class="in"/>
<path d="{line}" fill="none" stroke="url(#accent)" stroke-width="2.2" stroke-linecap="round" class="draw"/>
<circle cx="{pts[pi][0]:.1f}" cy="{pts[pi][1]:.1f}" r="4" fill="{t['bg']}" stroke="{ACCENT[1]}" stroke-width="2" class="in" style="animation-delay:1.2s"/>
<text x="{pts[pi][0]:.1f}" y="{pts[pi][1] - 12:.1f}" text-anchor="middle" font-size="11" font-weight="600" class="fg in" style="animation-delay:1.2s">peak {peak}</text>''')
    first = dt.date.fromisoformat(data["last_year"]["weeks"][0]["contributionDays"][0]["date"])
    body.append(f'<text x="{cx}" y="{cy + ch + 20}" font-size="10" class="muted">{first:%b %Y}</text>')
    body.append(f'<text x="{cx + cw}" y="{cy + ch + 20}" text-anchor="end" font-size="10" class="muted">Now</text>')

    # right: language breakdown
    lx, lw = 560, W - 32 - 560
    total = sum(s for s, _ in data["langs"].values()) or 1
    ranked = sorted(data["langs"].items(), key=lambda kv: -kv[1][0])
    top_langs = ranked[:6]
    other = total - sum(s for _, (s, _) in top_langs)
    if other > 0:
        top_langs.append(("Other", (other, "#6e7681")))
    body.append(f'<text x="{lx}" y="{cy + 4}" class="label" font-size="10">LANGUAGES</text>')
    body.append(f'<clipPath id="bar"><rect x="{lx}" y="{cy + 18}" width="{lw}" height="8" rx="4"/></clipPath><g clip-path="url(#bar)">')
    x = lx
    for name, (size, color) in top_langs:
        wdt = lw * size / total
        body.append(f'<rect x="{x:.1f}" y="{cy + 18}" width="{wdt + .5:.1f}" height="8" fill="{color}"/>')
        x += wdt
    body.append("</g>")
    for i, (name, (size, color)) in enumerate(top_langs):
        y = cy + 52 + i * 19
        body.append(f'''<g class="in" style="animation-delay:{.3 + i * .08:.2f}s">
  <circle cx="{lx + 5}" cy="{y - 4}" r="4.5" fill="{color}"/>
  <text x="{lx + 18}" y="{y}" font-size="12.5" class="fg">{escape(name)}</text>
  <text x="{lx + lw}" y="{y}" text-anchor="end" font-size="12" class="muted mono">{100 * size / total:.1f}%</text>
</g>''')
    css = (".draw{stroke-dasharray:2000;stroke-dashoffset:2000;animation:draw 1.6s ease-out forwards}"
           "@keyframes draw{to{stroke-dashoffset:0}}")
    return card(h, "\n".join(body), t, css)


def stack_card(t):
    row_h, y0, label_w = 44, 66, 150
    body = [header("Stack", "tools I reach for", t)]
    for r, (group, items) in enumerate(STACK):
        y = y0 + r * row_h
        if r:
            body.append(f'<line x1="32" x2="{W - 32}" y1="{y - 14}" y2="{y - 14}" stroke="{t["line"]}"/>')
        body.append(f'<text x="32" y="{y + 13}" font-size="13" font-weight="600" class="fg">{group}</text>')
        x = 32 + label_w
        for i, (name, color) in enumerate(items):
            cw = 30 + len(name) * 6.5
            body.append(f'''<g class="in" style="animation-delay:{.05 * (r * 7 + i):.2f}s">
  <rect x="{x:.1f}" y="{y - 2}" width="{cw:.1f}" height="24" rx="12" fill="{t['subtle']}" stroke="{t['border']}"/>
  <circle cx="{x + 13:.1f}" cy="{y + 10}" r="3.5" fill="{color}"/>
  <text x="{x + 22:.1f}" y="{y + 14}" font-size="12" class="fg">{escape(name)}</text>
</g>''')
            x += cw + 8
    return card(y0 + len(STACK) * row_h - 4, "\n".join(body), t)


def main():
    data = fetch()
    OUT.mkdir(exist_ok=True)
    for name, t in THEMES.items():
        (OUT / f"stats-{name}.svg").write_text(stats_card(data, t))
        (OUT / f"heatmap-{name}.svg").write_text(heatmap_card(data, t))
        (OUT / f"insights-{name}.svg").write_text(insights_card(data, t))
        (OUT / f"stack-{name}.svg").write_text(stack_card(t))
    print("rendered", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
