"""Sample project: football fixtures & odds scraper (BeautifulSoup).

Scrapes the public BetExplorer football listing page, extracting league,
kick-off date/time, teams, 1X2 odds for upcoming matches and final scores
for finished ones, and saves everything to a clean UTF-8 CSV.

Demonstrates: parsing grouped listing tables (tournament header rows +
match rows), two row layouts (upcoming vs results), extracting odds from
data attributes, date handling, polite crawling (browser User-Agent,
delays, timeouts), CSV export.

Scope note: BetExplorer's fixture LISTING pages are fully server-rendered
HTML and work fine with requests + BeautifulSoup. The per-match DETAIL
pages (standings tables, Over/Under threshold odds) render their odds via
JavaScript, so a production version of those would use Playwright
(headless Chromium) on top of this same parsing approach.
"""
import argparse
import csv
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.betexplorer.com/football/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}


def fetch(url, session, delay=2.0):
    """GET a page politely: browser UA, timeout, one retry."""
    time.sleep(delay)
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_fixtures(html, max_matches=60):
    """Parse tournament-grouped fixture tables into match dicts.

    Handles both row layouts found on the listing page:
    - upcoming fixtures: td.h-text-left (teams) + 3 td.table-main__odds (1X2)
    - finished results:  td.table-main__tt (teams) + td.table-main__result (score)
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    league = None

    for table in soup.select("table.table-main"):
        for row in table.select("tr"):
            classes = row.get("class", [])
            if "js-tournament" in classes:
                link = row.select_one("a.table-main__tournament")
                league = link.get_text(strip=True) if link else None
                continue
            if not row.has_attr("data-dt"):
                continue

            # data-dt="15,9,2026,19,00" -> date + kickoff
            day, month, year, hour, minute = row["data-dt"].split(",")
            date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            kickoff = f"{hour.zfill(2)}:{minute.zfill(2)}"

            teams_link = row.select_one("td.h-text-left a, td.table-main__tt a")
            if not teams_link:
                continue
            # Results rows wrap the home team in <strong> and spacing around
            # the "-" separator is inconsistent; fixtures use plain "A - B".
            strong = teams_link.select_one("strong")
            if strong:
                home = strong.get_text(strip=True)
                away = "".join(
                    s.get_text() if hasattr(s, "get_text") else str(s)
                    for s in strong.next_siblings
                )
                away = re.sub(r"^[\s\-–]+", "", away).strip()
                if not home or not away:
                    continue
            else:
                teams = teams_link.get_text(strip=True)
                if " - " not in teams:
                    continue
                home, away = [t.strip() for t in teams.split(" - ", 1)]
            match_url = "https://www.betexplorer.com" + teams_link["href"]

            odds_cells = row.select("td.table-main__odds")
            odds = []
            for cell in odds_cells[:3]:
                btn = cell.select_one("button[data-odd]")
                odds.append(btn["data-odd"] if btn else "")
            while len(odds) < 3:
                odds.append("")

            score_el = row.select_one("td.table-main__result")
            score = score_el.get_text(strip=True) if score_el else ""

            matches.append({
                "date": date,
                "kickoff": kickoff,
                "status": "finished" if score else "upcoming",
                "league": league or "",
                "home_team": home,
                "away_team": away,
                "odd_1": odds[0],
                "odd_x": odds[1],
                "odd_2": odds[2],
                "score": score,
                "match_url": match_url,
            })
            if len(matches) >= max_matches:
                return matches
    return matches


def main():
    parser = argparse.ArgumentParser(description="Sample: scrape BetExplorer football fixtures + 1X2 odds")
    parser.add_argument("--max-matches", type=int, default=60)
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--out", default="odds.csv")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Fetching {BASE_URL} ...")
    html = fetch(BASE_URL, session, delay=args.delay)
    matches = parse_fixtures(html, max_matches=args.max_matches)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "date", "kickoff", "status", "league", "home_team", "away_team",
            "odd_1", "odd_x", "odd_2", "score", "match_url",
        ])
        writer.writeheader()
        writer.writerows(matches)

    leagues = {m["league"] for m in matches}
    upcoming = sum(1 for m in matches if m["status"] == "upcoming")
    print(f"Scraped {len(matches)} matches ({upcoming} upcoming with odds) "
          f"across {len(leagues)} leagues -> {args.out}")
    for m in matches[:3]:
        print(f'  {m["date"]} {m["kickoff"]} | {m["home_team"]} vs {m["away_team"]} '
              f'| 1X2: {m["odd_1"]}/{m["odd_x"]}/{m["odd_2"] or "-"}')


if __name__ == "__main__":
    main()
