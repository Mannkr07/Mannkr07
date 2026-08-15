#!/usr/bin/env python3
"""
assets/dashboard.svg - an animated BI report over real GitHub contribution data.
Plays a one-shot load sequence (line draws, bars grow, KPIs count up), then rests.
"""
import json
import os
import math
import urllib.request
from datetime import datetime, timezone

USER = os.environ.get("GH_USER", "Mannkr07")
TOKEN = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN", "")

BG, CHROME, BORDER, GRID = "#0D1117", "#161B22", "#30363D", "#21262D"
TEXT, MUTED = "#E6EDF3", "#7D8590"
AMBER, CYAN, GREEN, RED = "#E3B341", "#56D4DD", "#7EE787", "#F85149"
RAMP = [AMBER, CYAN, GREEN, "#A5A5F5", "#F5A5C0", MUTED]
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

W = 880
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "profile-dashboard", "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _graphql(q):
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=json.dumps({"query": q}).encode(),
        headers={"User-Agent": "profile-dashboard", "Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _viewer_is_user():
    """True when the token authenticates as USER, so private repos are visible."""
    if not TOKEN:
        return False
    try:
        return _get("https://api.github.com/user").get("login", "").lower() == USER.lower()
    except Exception:
        return False


def _list_repos(owned):
    base = ("https://api.github.com/user/repos?affiliation=owner&per_page=100&page="
            if owned else f"https://api.github.com/users/{USER}/repos?per_page=100&page=")
    repos, page = [], 1
    while True:
        batch = _get(base + str(page))
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    return repos


def collect():
    user = _get(f"https://api.github.com/users/{USER}")
    owned = _viewer_is_user()
    repos = _list_repos(owned)

    public = sum(1 for r in repos if not r.get("private"))
    private = sum(1 for r in repos if r.get("private"))
    if not owned:                       # token can't see private repos at all
        public = user.get("public_repos", public)
        private = 0

    langs = {}
    for r in repos:
        if r.get("fork"):
            continue
        try:
            for n, sz in _get(r["languages_url"]).items():
                langs[n] = langs.get(n, 0) + sz
        except Exception:
            pass

    days = []
    try:
        d = _graphql(f'''{{ user(login:"{USER}") {{ contributionsCollection {{
            contributionCalendar {{ weeks {{ contributionDays {{
            date contributionCount weekday }} }} }} }} }} }}''')
        for wk in d["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            days += wk["contributionDays"]
    except Exception as e:
        print("calendar unavailable:", e)

    return {"days": days,
            "repos": public + private,
            "public": public,
            "private": private,
            "sees_private": owned,
            "stars": sum(r.get("stargazers_count", 0) for r in repos),
            "followers": user.get("followers", 0),
            "langs": sorted(langs.items(), key=lambda kv: -kv[1])}


def derive(s):
    days = s["days"]
    total = sum(d["contributionCount"] for d in days)
    active = sum(1 for d in days if d["contributionCount"] > 0)

    monthly, weekday = {}, [0] * 7
    for d in days:
        monthly[d["date"][:7]] = monthly.get(d["date"][:7], 0) + d["contributionCount"]
        weekday[(d["weekday"] + 6) % 7] += d["contributionCount"]

    keys = sorted(monthly)[-12:]
    series = [(MONTHS[int(k[5:7]) - 1], monthly[k]) for k in keys]

    best = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        best = max(best, run)

    busiest = max(keys, key=lambda k: monthly[k]) if keys else ""
    return {**s, "total": total, "active": active, "series": series, "weekday": weekday,
            "streak": best,
            "peak": max((d["contributionCount"] for d in days), default=0),
            "busiest": (MONTHS[int(busiest[5:7]) - 1] + " " + busiest[:4]) if busiest else "-",
            "avg": round(total / active, 1) if active else 0,
            "consistency": round(100 * active / len(days)) if days else 0}


def esc(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, size=12.5, fill=TEXT, anchor="start", weight="400", ls=None):
    e = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{e}>{esc(s)}</text>')


def enter(begin, dy=10):
    return (f'<animate attributeName="opacity" from="0" to="1" begin="{begin}s" '
            f'dur="0.55s" fill="freeze"/>'
            f'<animateTransform attributeName="transform" type="translate" from="0 {dy}" '
            f'to="0 0" begin="{begin}s" dur="0.55s" fill="freeze" calcMode="spline" '
            f'keyTimes="0;1" keySplines="0.16 0.84 0.24 1"/>')


def count_up(x, y, final, begin, size, steps=14):
    """numeric tick-up, the way a dashboard tile settles"""
    try:
        target = int(final)
    except (TypeError, ValueError):
        return (f'<g opacity="0">{enter(begin)}'
                f'{txt(x, y, final, size, AMBER, weight="600")}</g>')
    dur, out = 0.9, []
    vals = [int(round(target * (1 - math.pow(1 - (i + 1) / steps, 3)))) for i in range(steps)]
    vals[-1] = target

    seq = []                       # dedupe, but the target must always survive
    for i, v in enumerate(vals):
        if not seq or seq[-1][0] != v:
            seq.append((v, i))
    if seq[-1][0] != target:
        seq.append((target, steps - 1))

    for j, (v, i) in enumerate(seq):
        sets = f'<set attributeName="opacity" to="1" begin="{begin + dur*i/steps:.2f}s"/>'
        if j < len(seq) - 1:
            nxt = seq[j + 1][1]
            sets += f'<set attributeName="opacity" to="0" begin="{begin + dur*nxt/steps:.2f}s"/>'
        out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO}" font-size="{size}" '
                   f'fill="{AMBER}" font-weight="600" opacity="0">{esc(v)}{sets}</text>')
    return "".join(out)


def render(s):
    d, p = s, []
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y")

    p.append(f'<path d="M0.5 10.5a10 10 0 0 1 10-10h859a10 10 0 0 1 10 10V46H0.5Z" fill="{CHROME}"/>')
    p.append(f'<line x1="0.5" y1="46" x2="{W-0.5}" y2="46" stroke="{BORDER}"/>')
    for i, c in enumerate((RED, AMBER, GREEN)):
        p.append(f'<circle cx="{26+i*20}" cy="23.5" r="5.5" fill="{c}" opacity=".85"/>')
    p.append(txt(96, 28, "contribution analytics", 12.5, TEXT))
    p.append(txt(W - 26, 28, f"refreshed {stamp}", 11.5, MUTED, anchor="end"))

    # ---------------- KPI tiles ----------------
    kpis = [("total contributions", d["total"], "past 12 months"),
            ("active days", d["active"], f'of {len(d["days"])}'),
            ("longest streak", d["streak"], "consecutive days"),
            ("total repos", d["repos"],
             f'{d["public"]} public \u00b7 {d["private"]} private'
             if d.get("private") else f'{d["stars"]} stars earned')]
    ty, th = 66, 96
    tw = (W - 56 - 3 * 12) / 4
    for i, (label, val, sub) in enumerate(kpis):
        x, b = 28 + i * (tw + 12), 0.15 + i * 0.11
        p.append(f'<g opacity="0">{enter(b)}'
                 f'<rect x="{x:.1f}" y="{ty}" width="{tw:.1f}" height="{th}" rx="8" '
                 f'fill="{CHROME}" stroke="{BORDER}"/>'
                 f'{txt(x+16, ty+26, label, 11, MUTED)}'
                 f'{txt(x+16, ty+82, sub, 10.5, MUTED)}</g>')
        p.append(count_up(x + 16, ty + 64, val, b + 0.35, 30))

    y = ty + th + 30
    cw, ch, cx, cy = 520, 150, 28, ty + th + 60

    # ---------------- monthly trend ----------------
    p.append(txt(cx, y + 8, "contributions by month", 12, MUTED, ls="1.1"))
    series = d["series"] or [("", 0)]
    peak = max(v for _, v in series) or 1
    step = cw / max(len(series) - 1, 1)
    for g in range(5):
        gy = cy + ch - ch * g / 4
        p.append(f'<line x1="{cx}" y1="{gy:.1f}" x2="{cx+cw}" y2="{gy:.1f}" stroke="{GRID}"/>')
        p.append(txt(cx - 8, gy + 4, round(peak * g / 4), 10, MUTED, anchor="end"))

    pts = [(cx + i * step, cy + ch - ch * v / peak) for i, (_, v) in enumerate(series)]
    line = "M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in pts)
    length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) or 1

    p.append(f'<path d="{line} L{pts[-1][0]:.1f} {cy+ch} L{pts[0][0]:.1f} {cy+ch} Z" '
             f'fill="url(#area)" opacity="0">'
             f'<animate attributeName="opacity" from="0" to="1" begin="1.75s" dur="0.7s" fill="freeze"/></path>')

    solid = "M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in pts[:-1])
    p.append(f'<path d="{solid}" fill="none" stroke="{AMBER}" stroke-width="2" '
             f'stroke-linejoin="round" stroke-linecap="round" '
             f'stroke-dasharray="{length:.0f}" stroke-dashoffset="{length:.0f}">'
             f'<animate attributeName="stroke-dashoffset" from="{length:.0f}" to="0" '
             f'begin="0.75s" dur="1.15s" fill="freeze" calcMode="spline" keyTimes="0;1" '
             f'keySplines="0.35 0 0.2 1"/></path>')
    p.append(f'<path d="M{pts[-2][0]:.1f} {pts[-2][1]:.1f} L{pts[-1][0]:.1f} {pts[-1][1]:.1f}" '
             f'fill="none" stroke="{AMBER}" stroke-width="2" stroke-dasharray="4 3" '
             f'opacity="0" stroke-linecap="round">'
             f'<animate attributeName="opacity" from="0" to=".6" begin="1.9s" dur="0.4s" fill="freeze"/></path>')

    for i, (a, b) in enumerate(pts):
        p.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="3" fill="{BG}" stroke="{AMBER}" '
                 f'stroke-width="2" opacity="0">'
                 f'<animate attributeName="opacity" from="0" to="1" '
                 f'begin="{0.8 + i*0.09:.2f}s" dur="0.3s" fill="freeze"/></circle>')
        if i % 2 == 0 or i == len(pts) - 1:
            p.append(txt(a, cy + ch + 18, series[i][0], 10, MUTED, anchor="middle"))
    p.append(txt(cx, cy + ch + 36, "dashed segment = current month, incomplete", 10, MUTED))

    # ---------------- weekday bars ----------------
    bx, bw2 = 596, W - 596 - 28
    p.append(txt(bx, y + 8, "by weekday", 12, MUTED, ls="1.1"))
    wmax = max(d["weekday"]) or 1
    slot = bw2 / 7
    for i, v in enumerate(d["weekday"]):
        bh = max((ch - 4) * v / wmax, 2)
        bxx = bx + i * slot + slot * 0.22
        b0 = 1.15 + i * 0.07
        p.append(f'<rect x="{bxx:.1f}" y="{cy+ch:.1f}" width="{slot*0.56:.1f}" height="0" '
                 f'rx="3" fill="{CYAN if v == wmax else "#243b46"}">'
                 f'<animate attributeName="height" from="0" to="{bh:.1f}" begin="{b0:.2f}s" '
                 f'dur="0.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="0.16 0.84 0.24 1"/>'
                 f'<animate attributeName="y" from="{cy+ch:.1f}" to="{cy+ch-bh:.1f}" begin="{b0:.2f}s" '
                 f'dur="0.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="0.16 0.84 0.24 1"/></rect>')
        p.append(txt(bxx + slot * 0.28, cy + ch + 18, DAYS[i], 10, MUTED, anchor="middle"))

    y = cy + ch + 56
    p.append(f'<line x1="28" y1="{y}" x2="{W-28}" y2="{y}" stroke="{BORDER}"/>')
    y += 28

    # ---------------- languages (left) ----------------
    p.append(txt(28, y, "language distribution", 12, MUTED, ls="1.1"))
    top = d["langs"][:6]
    tot = sum(v for _, v in d["langs"]) or 1
    lw, lx, ry0 = 268, 150, y + 22
    for i, (name, val) in enumerate(top):
        pct = 100 * val / tot
        ry = ry0 + i * 28
        p.append(txt(28, ry + 11, name, 12, TEXT))
        p.append(f'<rect x="{lx}" y="{ry}" width="{lw}" height="14" rx="4" fill="{GRID}"/>')
        p.append(f'<rect x="{lx}" y="{ry}" width="0" height="14" rx="4" '
                 f'fill="{RAMP[i % len(RAMP)]}">'
                 f'<animate attributeName="width" from="0" to="{max(lw*pct/100,3):.1f}" '
                 f'begin="{1.9 + i*0.09:.2f}s" dur="0.7s" fill="freeze" calcMode="spline" '
                 f'keyTimes="0;1" keySplines="0.16 0.84 0.24 1"/></rect>')
        p.append(txt(lx + lw + 12, ry + 11, f"{pct:.1f}%", 11.5, MUTED))

    # ---------------- derived metrics (right) ----------------
    mx = 560
    p.append(txt(mx, y, "derived", 12, MUTED, ls="1.1"))
    metrics = [("busiest month", d["busiest"]),
               ("peak single day", f'{d["peak"]} commits'),
               ("avg per active day", d["avg"]),
               ("consistency", f'{d["consistency"]}% of days')]
    for i, (k, v) in enumerate(metrics):
        ry = ry0 + i * 28
        p.append(f'<g opacity="0">{enter(2.1 + i*0.1, 6)}'
                 f'{txt(mx, ry + 11, k, 12, MUTED)}'
                 f'{txt(W - 28, ry + 11, v, 12.5, CYAN, anchor="end")}</g>')
        if i < len(metrics) - 1:
            p.append(f'<line x1="{mx}" y1="{ry+22:.0f}" x2="{W-28}" y2="{ry+22:.0f}" stroke="{GRID}"/>')

    H = ry0 + max(len(top), len(metrics)) * 28 + 14
    defs = (f'<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{AMBER}" stop-opacity=".22"/>'
            f'<stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></linearGradient></defs>')
    frame = (f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="10" '
             f'fill="{BG}" stroke="{BORDER}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}" height="{H}" role="img" '
            f'aria-label="GitHub contribution analytics dashboard">\n{defs}\n{frame}\n  '
            + "\n  ".join(p) + "\n</svg>\n")


if __name__ == "__main__":
    data = derive(collect())
    os.makedirs("assets", exist_ok=True)
    open("assets/dashboard.svg", "w").write(render(data))
    print(f'wrote assets/dashboard.svg  ({data["total"]} contributions)')
