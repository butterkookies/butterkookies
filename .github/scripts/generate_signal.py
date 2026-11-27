#!/usr/bin/env python3
"""Generate the live Warm Espresso & Butter-Cookie GitHub Signal SVG card.

Uses only Python's standard library so GitHub Actions can execute it directly
without installing extra packages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        primaryLanguage { name }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""

# Harmonized Warm Espresso & Butter-Cookie swatch palette for language breakdown
LANG_SWATCHES = [
    "#F0C69A",  # Buttercream Gold
    "#D48A52",  # Toasted Caramel
    "#78B3A0",  # Sunlit Botanical Jade
    "#DC8262",  # Warm Terracotta
    "#C29B76",  # Oat Latte
    "#7F634E",  # Roasted Mocha
]

MONTH_ABBR = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]


def fetch_github_data(username: str, token: str) -> dict:
    payload = json.dumps({
        "query": GRAPHQL_QUERY,
        "variables": {"login": username},
    }).encode("utf-8")

    req = urllib.request.Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{username}-profile-signal",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if "errors" in data:
        raise RuntimeError(f"GitHub GraphQL errors: {data['errors']}")
    return data


def compute_metrics(raw: dict) -> dict:
    user = raw["data"]["user"]
    repos = user["repositories"]["nodes"] or []
    repo_count = user["repositories"]["totalCount"]
    followers = user["followers"]["totalCount"]
    total_stars = sum(r.get("stargazerCount", 0) for r in repos)

    cal = user["contributionsCollection"]["contributionCalendar"]
    total_contributions = cal["totalContributions"]
    days = [
        day
        for week in cal["weeks"]
        for day in week["contributionDays"]
    ]

    active_days = sum(1 for d in days if d["contributionCount"] > 0)

    longest_streak = 0
    running = 0
    for d in days:
        if d["contributionCount"] > 0:
            running += 1
            if running > longest_streak:
                longest_streak = running
        else:
            running = 0

    # Aggregate contributions into the last 12 calendar months (ordered oldest -> newest)
    month_totals: dict[tuple[int, int], int] = defaultdict(int)
    for d in days:
        y, m, _ = map(int, d["date"].split("-"))
        month_totals[(y, m)] += d["contributionCount"]

    sorted_months = sorted(month_totals.keys())[-12:]
    monthly_series = [
        (MONTH_ABBR[m - 1], month_totals[(y, m)])
        for (y, m) in sorted_months
    ]

    # Language breakdown by primary language across non-fork public repositories
    lang_counts = Counter(
        r["primaryLanguage"]["name"]
        for r in repos
        if r.get("primaryLanguage") and r["primaryLanguage"].get("name")
    )
    tagged_repos = sum(lang_counts.values())
    top_langs = lang_counts.most_common(5)
    other_count = tagged_repos - sum(c for _, c in top_langs)
    if other_count > 0:
        top_langs.append(("Other", other_count))

    return {
        "login": user.get("login", "butterkookies"),
        "followers": followers,
        "repo_count": repo_count,
        "total_stars": total_stars,
        "total_contributions": total_contributions,
        "active_days": active_days,
        "longest_streak": longest_streak,
        "monthly_series": monthly_series,
        "top_langs": top_langs,
        "tagged_repos": tagged_repos,
    }


def fmt_int(n: int) -> str:
    return f"{n:,}"


def render_svg(metrics: dict, updated_date: str) -> str:
    login = html.escape(metrics["login"])
    kpis = [
        (fmt_int(metrics["total_contributions"]), "CONTRIBUTIONS · 12M", "#FAF0E4", "#D48A52"),
        (fmt_int(metrics["repo_count"]), "ORIGINAL REPOS", "#FAF0E4", "#F0C69A"),
        (fmt_int(metrics["active_days"]), "ACTIVE DAYS · 12M", "#FAF0E4", "#78B3A0"),
        (f"{metrics['longest_streak']}d", "BEST STREAK", "#F0C69A", "#DC8262"),
    ]

    kpi_parts = []
    kpi_w = 260
    kpi_gap = 18.67
    for idx, (val, label, val_color, dot_color) in enumerate(kpis):
        x = round(52 + idx * (kpi_w + kpi_gap), 2)
        kpi_parts.append(f"""
    <g transform="translate({x} 30)">
      <rect width="{kpi_w}" height="86" rx="14" fill="#120D0A" stroke="#E8B88A" stroke-opacity="0.15" stroke-width="1"/>
      <rect x="20" y="20" width="22" height="3" rx="1.5" fill="{dot_color}" opacity="0.9"/>
      <text x="20" y="55" fill="{val_color}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="30" font-weight="700" letter-spacing="-0.6">{html.escape(val)}</text>
      <text x="20" y="74" fill="#9A806A" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="11" font-weight="500" letter-spacing="1.4">{html.escape(label)}</text>
    </g>""")

    # 12-Month Contribution Rhythm bar chart (left bottom panel: x=52, y=134, w=586, h=148)
    monthly = metrics["monthly_series"]
    peak_val = max((v for _, v in monthly), default=1)
    peak_val = max(peak_val, 1)

    bar_parts = []
    chart_x0 = 24
    chart_bottom = 114
    max_bar_h = 56
    bar_w = 26
    bar_step = 45.5 if len(monthly) > 1 else 45.5
    # Subtle horizontal gridlines inside chart
    for gy in (58, 86, 114):
        bar_parts.append(
            f'      <line x1="20" y1="{gy}" x2="566" y2="{gy}" stroke="#E8B88A" stroke-opacity="0.07" stroke-width="1"/>'
        )

    for idx, (m_label, count) in enumerate(monthly):
        bx = round(chart_x0 + idx * bar_step, 2)
        bh = max(4, round((count / peak_val) * max_bar_h, 2)) if count > 0 else 3
        by = round(chart_bottom - bh, 2)
        fill = "url(#barPeak)" if count == peak_val and count > 0 else ("url(#barGrad)" if count > 0 else "#2A1F18")
        opacity = "1" if count > 0 else "0.55"
        bar_parts.append(
            f'      <rect x="{bx}" y="{by}" width="{bar_w}" height="{bh}" rx="5" fill="{fill}" opacity="{opacity}"/>'
        )
        bar_parts.append(
            f'      <text x="{round(bx + bar_w / 2, 2)}" y="132" text-anchor="middle" fill="#8F7560" font-family="\'SFMono-Regular\', ui-monospace, Consolas, monospace" font-size="10.5" letter-spacing="0.4">{html.escape(m_label)}</text>'
        )

    # Languages Across Public Repos (right bottom panel: x=658, y=134, w=490, h=148)
    top_langs = metrics["top_langs"]
    tagged_repos = max(metrics["tagged_repos"], 1)
    bar_total_w = 442
    seg_parts = []
    legend_parts = []
    cursor_x = 0.0

    for idx, (lang_name, count) in enumerate(top_langs):
        color = LANG_SWATCHES[idx % len(LANG_SWATCHES)]
        frac = count / tagged_repos
        seg_w = round(bar_total_w - cursor_x, 2) if idx == len(top_langs) - 1 else round(frac * bar_total_w, 2)
        seg_parts.append(
            f'        <rect x="{round(cursor_x, 2)}" y="0" width="{max(seg_w, 2)}" height="11" fill="{color}"/>'
        )
        cursor_x += seg_w

        col = idx % 2
        row = idx // 2
        lx = 24 if col == 0 else 258
        val_x = 202 if col == 0 else 208
        ly = 84 + row * 24
        pct = round(frac * 100)
        safe_name = html.escape(lang_name)
        legend_parts.append(f"""      <g transform="translate({lx} {ly})">
        <circle cx="5" cy="-4" r="4" fill="{color}"/>
        <text x="16" y="0" fill="#EAD7C5" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="12.5" font-weight="500">{safe_name}</text>
        <text x="{val_x}" y="0" text-anchor="end" fill="#9A806A" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="11.5">{count} · {pct}%</text>
      </g>""")

    return f"""<svg width="1200" height="316" viewBox="0 0 1200 316" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="sig-title sig-desc">
  <title id="sig-title">{login} — GitHub Signal &amp; Rhythm</title>
  <desc id="sig-desc">Live GitHub contribution metrics, 12-month activity rhythm, and primary languages across public repositories.</desc>
  <defs>
    <linearGradient id="sigBg" x1="0" y1="0" x2="1200" y2="316" gradientUnits="userSpaceOnUse">
      <stop stop-color="#140F0B"/>
      <stop offset="0.55" stop-color="#1B140F"/>
      <stop offset="1" stop-color="#231912"/>
    </linearGradient>
    <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
      <stop stop-color="#E3A168"/>
      <stop offset="1" stop-color="#8C4C26"/>
    </linearGradient>
    <linearGradient id="barPeak" x1="0" y1="0" x2="0" y2="1">
      <stop stop-color="#F7D5AE"/>
      <stop offset="1" stop-color="#C87741"/>
    </linearGradient>
    <pattern id="sigGrid" width="32" height="32" patternUnits="userSpaceOnUse">
      <path d="M32 0H0V32" stroke="#F4DAC0" stroke-opacity="0.036"/>
    </pattern>
    <clipPath id="sigFrame">
      <rect width="1200" height="316" rx="24"/>
    </clipPath>
    <clipPath id="langBarClip">
      <rect width="{bar_total_w}" height="11" rx="5.5"/>
    </clipPath>
  </defs>

  <g clip-path="url(#sigFrame)">
    <rect width="1200" height="316" fill="url(#sigBg)"/>
    <rect width="1200" height="316" fill="url(#sigGrid)"/>

    <!-- KPI Row -->{"".join(kpi_parts)}

    <!-- Left Bottom Panel: 12-Month Rhythm -->
    <g transform="translate(52 134)">
      <rect width="586" height="148" rx="14" fill="#120D0A" stroke="#E8B88A" stroke-opacity="0.15" stroke-width="1"/>
      <text x="22" y="29" fill="#D48A52" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="11.5" font-weight="600" letter-spacing="2">12-MONTH RHYTHM</text>
      <text x="564" y="29" text-anchor="end" fill="#8F7560" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="11" letter-spacing="1">PEAK {fmt_int(peak_val)} / MO</text>
{chr(10).join(bar_parts)}
    </g>

    <!-- Right Bottom Panel: Languages Across Public Repos -->
    <g transform="translate(658 134)">
      <rect width="490" height="148" rx="14" fill="#120D0A" stroke="#E8B88A" stroke-opacity="0.15" stroke-width="1"/>
      <text x="24" y="29" fill="#D48A52" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="11.5" font-weight="600" letter-spacing="2">REPO LANGUAGES</text>
      <text x="466" y="29" text-anchor="end" fill="#8F7560" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="11" letter-spacing="1">{metrics['tagged_repos']} TAGGED PUBLIC REPOS</text>
      <g transform="translate(24 46)" clip-path="url(#langBarClip)">
        <rect width="{bar_total_w}" height="11" fill="#251B14"/>
{chr(10).join(seg_parts)}
      </g>
{chr(10).join(legend_parts)}
    </g>

    <!-- Subtle sync caption -->
    <text x="600" y="302" text-anchor="middle" fill="#7D6552" font-family="'SFMono-Regular', ui-monospace, Consolas, monospace" font-size="10.5" letter-spacing="1.6">AUTO-SYNCED DAILY VIA GITHUB ACTIONS  ·  @{login.upper()}  ·  UPDATED {html.escape(updated_date)}</text>
  </g>

  <rect x="1" y="1" width="1198" height="314" rx="23" stroke="#E8B88A" stroke-opacity="0.2" stroke-width="1.5"/>
</svg>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GitHub Signal SVG")
    parser.add_argument("--username", default=os.environ.get("GITHUB_USERNAME", "butterkookies"))
    parser.add_argument("--output", required=True, help="Output SVG file path")
    parser.add_argument("--input-json", help="Optional pre-fetched GraphQL JSON path")
    args = parser.parse_args()

    if args.input_json:
        raw = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    else:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            print("Error: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
            return 1
        raw = fetch_github_data(args.username, token)

    metrics = compute_metrics(raw)
    updated_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d UTC")
    svg = render_svg(metrics, updated_date)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    print(f"Wrote {out_path} ({len(svg)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
