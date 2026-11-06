"""Render the ERAGON.MX stat strip for the org profile README.

Pulls public numbers for the org from the GitHub API and writes
profile/assets/metrics-dark.svg and metrics-light.svg. Text is converted
to outlines, so the SVGs look the same everywhere with no fonts needed.

Run by .github/workflows/metrics.yml. To try it locally:
    pip install fonttools
    ORG=your-org python scripts/metrics.py
"""
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = Path(__file__).resolve().parent / "fonts"
OUT = ROOT / "profile" / "assets"

# Tokens from the ERAGON.MX design system
ORANGE = "#FF5A0A"
ON_ORANGE = "#0D0B0A"
THEMES = {
    "dark": dict(panel="#171311", line="#2A2420", ink="#F6F2EE", muted="#A39A92", label=ORANGE),
    "light": dict(panel="#FFFFFF", line="#D8D1CA", ink="#0D0B0A", muted="#5E564F", label="#0D0B0A"),
}

FONT = {
    "display": TTFont(FONTS / "Teko-Bold.ttf"),
    "label": TTFont(FONTS / "BarlowCondensed-Bold.ttf"),
}


# --- data -------------------------------------------------------------------

def fetch_repos(org):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "eragon-metrics"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    repos, page = [], 1
    while True:
        url = f"https://api.github.com/orgs/{org}/repos?type=public&per_page=100&page={page}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
            batch = json.load(r)
        repos += batch
        if len(batch) < 100:
            return repos
        page += 1


def summarize(repos):
    # Count real builds only: skip forks, archived repos and this profile repo
    builds = [r for r in repos if not r["fork"] and not r["archived"] and r["name"] != ".github"]
    pushed = [dt.datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00")) for r in builds if r.get("pushed_at")]
    return {
        "builds": len(builds),
        "stars": sum(r["stargazers_count"] for r in builds),
        "forks": sum(r["forks_count"] for r in builds),
        "last": max(pushed) if pushed else None,
    }


def short(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


# --- drawing ----------------------------------------------------------------

def text(s, font, size, x, y, fill, track=0.0, anchor="start"):
    """Outlined text. y is the baseline, track is letter spacing in em."""
    f = FONT[font]
    gs, cmap, upm, hm = f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm, f["hmtx"]
    sc, adv, parts = size / upm, 0, []
    names = [cmap[ord(c)] for c in s]
    for i, g in enumerate(names):
        pen = SVGPathPen(gs)
        gs[g].draw(pen)
        if pen.getCommands():
            parts.append((adv, pen.getCommands()))
        adv += hm[g][0] + (track * upm if i < len(names) - 1 else 0)
    w = adv * sc
    x0 = {"start": x, "middle": x - w / 2, "end": x - w}[anchor]
    paths = "".join(
        f'<path transform="translate({x0 + a * sc:.2f} {y:.2f}) scale({sc:.5f} {-sc:.5f})" d="{d}"/>'
        for a, d in parts
    )
    return f'<g fill="{fill}">{paths}</g>'


def cap(font, size):
    f = FONT[font]
    pen = BoundsPen(f.getGlyphSet())
    f.getGlyphSet()[f.getBestCmap()[ord("E")]].draw(pen)
    return pen.bounds[3] * size / f["head"].unitsPerEm


def slash(x, y, h=10, w=20, fill=ORANGE):
    off = h * 0.577  # short bar skewed -30 degrees
    return f'<polygon points="{x + off:.1f},{y} {x + w + off:.1f},{y} {x + w:.1f},{y + h} {x},{y + h}" fill="{fill}"/>'


def tile(x, w, h, label, value, t, lead=False, sub=None):
    fill = ORANGE if lead else t["panel"]
    stroke = "none" if lead else t["line"]
    ink = ON_ORANGE if lead else t["ink"]
    lab = ON_ORANGE if lead else t["label"]
    pad = 24
    s = f'<rect x="{x + 0.5}" y="0.5" width="{w - 1}" height="{h - 1}" rx="8" fill="{fill}" stroke="{stroke}"/>'
    s += slash(x + pad, pad + 2, h=14, w=24, fill=ON_ORANGE if lead else ORANGE)
    s += text(label, "label", 21, x + pad + 44, pad + 16, lab, track=0.18)
    size = 112
    s += text(value, "display", size, x + pad - 4, pad + 40 + cap("display", size), ink)
    if sub:
        s += text(sub, "label", 19, x + w - pad, h - pad, ON_ORANGE if lead else t["muted"], track=0.18, anchor="end")
    return s


def strip(stats, theme):
    t = THEMES[theme]
    W, H, gap = 1280, 200, 16
    w = (W - gap * 3) / 4
    last = stats["last"]
    tiles = [
        ("BUILDS", str(stats["builds"]), True, "OPEN SOURCE"),
        ("STARS", short(stats["stars"]), False, None),
        ("FORKS", short(stats["forks"]), False, None),
        ("LAST PUSH", str(last.day) if last else "-", False, last.strftime("%b %Y").upper() if last else None),
    ]
    body = "".join(tile(i * (w + gap), w, H, *tl[:2], t, lead=tl[2], sub=tl[3]) for i, tl in enumerate(tiles))
    alt = f'{stats["builds"]} builds, {stats["stars"]} stars, {stats["forks"]} forks'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" aria-label="{alt}"><title>{alt}</title>{body}</svg>')


def main():
    org = os.environ.get("ORG") or os.environ["GITHUB_REPOSITORY_OWNER"]
    stats = summarize(fetch_repos(org))
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (OUT / f"metrics-{theme}.svg").write_text(strip(stats, theme))
    print(f"{org}: {stats['builds']} builds, {stats['stars']} stars, {stats['forks']} forks, last push {stats['last']}")


if __name__ == "__main__":
    main()
