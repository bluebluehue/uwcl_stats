#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path("data/uwcl")
RAW_SQUAD_DIR = (
    DATA_DIR / "raw" / "squads"
)

OUTPUT_PATH = (
    DATA_DIR
    / "nationalities_master.json"
)

ARCHIVE_PATH = (
    DATA_DIR
    / "archive"
    / "2026-09-21-preseason"
    / "nationalities_master.json"
)

UEFA_BASE = (
    "https://www.uefa.com/"
    "womenschampionsleague/clubs"
)

TEAMS = {
    "ARS": {
        "id": "81199",
        "name": "Arsenal",
    },
    "AUS": {
        "id": "2612002",
        "name": "Austria Wien",
    },
    "BAR": {
        "id": "2601945",
        "name": "Barcelona",
    },
    "BAY": {
        "id": "2600661",
        "name": "Bayern",
    },
    "BEN": {
        "id": "2610349",
        "name": "Benfica",
    },
    "CHE": {
        "id": "2600827",
        "name": "Chelsea",
    },
    "HAC": {
        "id": "2600867",
        "name": "Häcken",
    },
    "HBK": {
        "id": "2611087",
        "name": "HB Køge",
    },
    "INT": {
        "id": "2609776",
        "name": "Inter",
    },
    "JUV": {
        "id": "2609590",
        "name": "Juventus",
    },
    "MCI": {
        "id": "2603520",
        "name": "Man City",
    },
    "OHL": {
        "id": "2601983",
        "name": "OH Leuven",
    },
    "LYO": {
        "id": "2600241",
        "name": "OL Lyonnes",
    },
    "PAR": {
        "id": "2609779",
        "name": "Paris",
    },
    "PSG": {
        "id": "2600841",
        "name": "Paris SG",
    },
    "RMA": {
        "id": "2611347",
        "name": "Real Madrid",
    },
    "ROM": {
        "id": "2610208",
        "name": "Roma",
    },
    "SER": {
        "id": "2611086",
        "name": "Servette",
    },
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language":
        "en-US,en;q=0.9",
}

PLAYER_ID_RE = re.compile(
    r"/clubs/players/"
    r"(\d+)"
    r"(?:--[^/?#]+)?/?"
)

SESSION = requests.Session()
SESSION.headers.update(
    REQUEST_HEADERS
)


# ============================================================
# HELPERS
# ============================================================

def utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def clean_string(
    value: Any,
) -> str:
    if value is None:
        return ""

    return str(value).strip()


def write_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            indent=2,
        )

        handle.write("\n")


def fetch_page(
    url: str,
) -> str:
    last_error = None

    for attempt in range(
        1,
        4,
    ):
        try:
            print(
                f"Fetching {url} "
                f"(attempt {attempt}/3)",
                flush=True,
            )

            response = SESSION.get(
                url,
                timeout=(15, 45),
            )

            response.raise_for_status()

            return response.text

        except (
            requests.exceptions.RequestException
        ) as exc:
            last_error = exc

            print(
                f"WARNING: {exc}",
                flush=True,
            )

            if attempt < 3:
                time.sleep(
                    attempt * 2
                )

    raise RuntimeError(
        f"Could not fetch {url}"
    ) from last_error


# ============================================================
# PARSER
# ============================================================

def parse_squad(
    html: str,
    *,
    team_id: str,
    team_name: str,
    team_code: str,
) -> list[dict[str, str]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results = []
    seen = set()

    rows = soup.select(
        "pk-table-row.row--squadlist"
    )

    for row in rows:
        link = row.find(
            "a",
            href=PLAYER_ID_RE,
        )

        if not link:
            continue

        href = clean_string(
            link.get("href")
        )

        match = PLAYER_ID_RE.search(
            href
        )

        if not match:
            continue

        player_id = match.group(1)

        if player_id in seen:
            continue

        name_node = link.find(
            attrs={
                "itemprop": "name"
            }
        )

        player_name = clean_string(
            name_node.get_text(
                " ",
                strip=True,
            )
            if name_node
            else link.get("title")
        )

        nationality_node = row.find(
            attrs={
                "column-key":
                    "nationality"
            }
        )

        if nationality_node:
            nationality = clean_string(
                nationality_node.get_text(
                    " ",
                    strip=True,
                )
            )
        else:
            country_node = link.find(
                attrs={
                    "itemprop":
                        "country"
                }
            )

            nationality = clean_string(
                country_node.get_text(
                    " ",
                    strip=True,
                )
                if country_node
                else ""
            )

        nationality = (
            nationality.upper()
        )

        if not nationality:
            continue

        seen.add(player_id)

        results.append(
            {
                "player_id":
                    player_id,

                "name":
                    player_name,

                "nationality":
                    nationality,

                "team_id":
                    team_id,

                "team":
                    team_name,

                "team_code":
                    team_code,
            }
        )

    return results


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    RAW_SQUAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_players = []
    failed_teams = []

    for team_code, team in (
        TEAMS.items()
    ):
        team_id = team["id"]
        team_name = team["name"]

        url = (
            f"{UEFA_BASE}/"
            f"{team_id}/squad/"
        )

        try:
            html = fetch_page(url)

        except Exception as exc:
            print(
                f"ERROR: {team_code} "
                f"failed: {exc}",
                flush=True,
            )

            failed_teams.append(
                team_code
            )

            continue

        raw_path = (
            RAW_SQUAD_DIR
            / f"{team_code}.html"
        )

        raw_path.write_text(
            html,
            encoding="utf-8",
        )

        players = parse_squad(
            html,
            team_id=team_id,
            team_name=team_name,
            team_code=team_code,
        )

        print(
            f"{team_code}: "
            f"{len(players)} players",
            flush=True,
        )

        all_players.extend(
            players
        )

    all_players.sort(
        key=lambda p: (
            p["nationality"],
            p["name"],
            p["player_id"],
        )
    )

    nationality_codes = sorted(
        {
            p["nationality"]
            for p in all_players
        }
    )

    payload = {
        "competition":
            "UWCL",

        "season":
            "2026/27",

        "source":
            "UEFA squad pages",

        "generated_at_utc":
            utc_now_iso(),

        "team_count":
            len(TEAMS),

        "successful_team_count":
            (
                len(TEAMS)
                - len(failed_teams)
            ),

        "player_count":
            len(all_players),

        "nationality_count":
            len(nationality_codes),

        "nationalities":
            nationality_codes,

        "failed_teams":
            failed_teams,

        "players":
            all_players,
    }

    write_json(
        OUTPUT_PATH,
        payload,
    )

    if not ARCHIVE_PATH.exists():
        write_json(
            ARCHIVE_PATH,
            payload,
        )

        print(
            "Created permanent preseason "
            "nationality archive.",
            flush=True,
        )

    print()
    print(
        "Nationality fetch complete.",
        flush=True,
    )
    print(
        f"Players: "
        f"{len(all_players)}",
        flush=True,
    )
    print(
        f"Nationalities: "
        f"{len(nationality_codes)}",
        flush=True,
    )
    print(
        "Failed teams: "
        + (
            ", ".join(
                failed_teams
            )
            if failed_teams
            else "none"
        ),
        flush=True,
    )

    if failed_teams:
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise
