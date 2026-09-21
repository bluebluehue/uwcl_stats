#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://gaming.uefa.com/en/uwclfantasy/services/feeds"

URLS = {
    "players": f"{BASE_URL}/players/players_40_en_1.json",
    "teams": f"{BASE_URL}/teams/teams_40_en.json",
    "fixtures": f"{BASE_URL}/fixtures/fixtures_40_en.json",
}

UEFA_SQUAD_BASE = (
    "https://www.uefa.com/womenschampionsleague/clubs"
)

DATA_DIR = Path("data/uwcl")
RAW_DIR = DATA_DIR / "raw"
SQUAD_RAW_DIR = RAW_DIR / "squads"

PRESEASON_ARCHIVE_DIR = (
    DATA_DIR / "archive" / "2026-09-21-preseason"
)

CURRENT_SEASON = "2026/27"
HISTORICAL_STATS_SEASON = "2025/26"

POSITION_MAP = {
    1: "GK",
    2: "DEF",
    3: "MID",
    4: "FWD",
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/json,"
        "text/plain,*/*"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Connection timeout, read timeout.
REQUEST_TIMEOUT = (15, 120)

# Each request gets several chances before failing.
MAX_ATTEMPTS = 5


# ============================================================
# HTTP SESSION / RETRIES
# ============================================================

SESSION = requests.Session()
SESSION.headers.update(REQUEST_HEADERS)


def request_with_retries(
    url: str,
    *,
    required: bool = True,
) -> requests.Response | None:
    """
    Fetch a URL with explicit retries.

    Core fantasy feeds are required.
    Squad pages are optional enrichment and may fail without
    killing the entire fantasy-data update.
    """

    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(
                f"Fetching {url} "
                f"(attempt {attempt}/{MAX_ATTEMPTS})"
            )

            response = SESSION.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            return response

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
        ) as exc:
            last_error = exc

            print(
                f"WARNING: request failed on attempt "
                f"{attempt}: {exc}"
            )

            if attempt < MAX_ATTEMPTS:
                wait_seconds = 2 ** (attempt - 1)

                print(
                    f"Retrying in {wait_seconds}s..."
                )

                time.sleep(wait_seconds)

    if required:
        raise RuntimeError(
            f"Failed to fetch required URL after "
            f"{MAX_ATTEMPTS} attempts: {url}"
        ) from last_error

    print(
        f"WARNING: optional URL failed after "
        f"{MAX_ATTEMPTS} attempts; continuing: {url}"
    )

    return None


def fetch_json(url: str) -> dict[str, Any]:
    response = request_with_retries(
        url,
        required=True,
    )

    assert response is not None

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected top-level object from {url}, "
            f"got {type(payload).__name__}"
        )

    meta = payload.get("meta")

    if isinstance(meta, dict):
        if meta.get("success") is False:
            raise RuntimeError(
                f"UEFA feed reported failure for "
                f"{url}: {meta}"
            )

    return payload


def fetch_optional_text(
    url: str,
) -> str | None:
    response = request_with_retries(
        url,
        required=False,
    )

    if response is None:
        return None

    return response.text


# ============================================================
# GENERIC HELPERS
# ============================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    SQUAD_RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PRESEASON_ARCHIVE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


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
            sort_keys=False,
        )

        handle.write("\n")


def write_text(
    path: Path,
    value: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        value,
        encoding="utf-8",
    )


def clean_string(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def unwrap_number(
    value: Any,
    default: float | int | None = 0,
) -> Any:
    """
    UEFA sometimes gives us:

        9.5

    and sometimes:

        {
          "source": "9.5",
          "parsedValue": 9.5
        }

    Normalize both.
    """

    if isinstance(value, dict):
        if "parsedValue" in value:
            return value["parsedValue"]

        if "source" in value:
            raw = value["source"]

            try:
                return float(raw)
            except (TypeError, ValueError):
                return default

    if value is None:
        return default

    return value


def normalize_status(
    player: dict[str, Any],
) -> dict[str, Any]:
    code = clean_string(
        player.get("pStatus")
    )

    status_labels = {
        "I": "Injured",
        "D": "Doubtful",
        "S": "Suspended",
    }

    return {
        "code": code,
        "label": status_labels.get(
            code,
            "",
        ),
        "availability_text": clean_string(
            player.get("trained")
        ),
    }


def normalize_match_reference(
    match: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(match, dict):
        return None

    return {
        "matchday": clean_string(
            match.get("mdId")
        ),
        "team_id": clean_string(
            match.get("tId")
        ),
        "team": clean_string(
            match.get("tSCode")
        ),
        "team_code": clean_string(
            match.get("cCode")
        ),
        "home_away": clean_string(
            match.get("tLoc")
        ),
        "opponent_id": clean_string(
            match.get("vsTID")
        ),
        "opponent": clean_string(
            match.get("vsTSCode")
        ),
        "opponent_code": clean_string(
            match.get("vsCCode")
        ),
        "opponent_home_away": clean_string(
            match.get("vsTLoc")
        ),
        "kickoff": clean_string(
            match.get("matchDate")
        ),
    }


# ============================================================
# TEAM NORMALIZATION
# ============================================================

def normalize_team(
    team: dict[str, Any],
) -> dict[str, Any]:
    upcoming = (
        team.get("upcomingMatchesList")
        or []
    )

    return {
        "id": clean_string(
            team.get("id")
        ),
        "name": clean_string(
            team.get("webName")
            or team.get("offName")
        ),
        "official_name": clean_string(
            team.get("offName")
        ),
        "code": clean_string(
            team.get("shortName")
        ),
        "eliminated": team.get(
            "isEliminated"
        ),
        "pot": {
            "id": clean_string(
                team.get("htPtId")
            ),
            "name": clean_string(
                team.get("htPtName")
            ),
        },
        "next_match": (
            normalize_match_reference(
                upcoming[0]
            )
            if upcoming
            else None
        ),
    }


def normalize_teams(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    teams = (
        payload
        .get("data", {})
        .get("value", [])
    )

    if not isinstance(teams, list):
        raise ValueError(
            "Could not locate data.value "
            "in UEFA teams feed"
        )

    normalized = [
        normalize_team(team)
        for team in teams
        if isinstance(team, dict)
    ]

    normalized.sort(
        key=lambda team: team["name"]
    )

    return normalized


# ============================================================
# NATIONALITY SCRAPING
# ============================================================

PLAYER_ID_RE = re.compile(
    r"/clubs/players/(\d+)"
    r"(?:--[^/?#]+)?/?"
)


def parse_squad_nationalities(
    html: str,
    team_id: str,
    team_name: str,
    team_code: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

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

        match = PLAYER_ID_RE.search(href)

        if not match:
            continue

        player_id = match.group(1)

        if player_id in seen_ids:
            continue

        name_node = link.find(
            attrs={"itemprop": "name"}
        )

        if name_node:
            player_name = clean_string(
                name_node.get_text(
                    " ",
                    strip=True,
                )
            )
        else:
            player_name = clean_string(
                link.get("title")
            )

        nationality_node = row.find(
            attrs={
                "column-key": "nationality"
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
                    "itemprop": "country"
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

        nationality = nationality.upper()

        if not nationality:
            continue

        seen_ids.add(player_id)

        results.append(
            {
                "player_id": player_id,
                "name": player_name,
                "nationality": nationality,
                "team_id": team_id,
                "team": team_name,
                "team_code": team_code,
            }
        )

    return results


def load_existing_nationality_lookup(
) -> dict[str, dict[str, Any]]:
    """
    Preserve previously discovered nationality data if a
    future UEFA squad-page request temporarily fails.
    """

    path = DATA_DIR / "nationalities.json"

    if not path.exists():
        return {}

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        print(
            "WARNING: could not read existing "
            f"nationalities.json: {exc}"
        )
        return {}

    lookup: dict[
        str,
        dict[str, Any],
    ] = {}

    for record in payload.get(
        "players",
        [],
    ):
        if not isinstance(record, dict):
            continue

        player_id = clean_string(
            record.get("player_id")
        )

        nationality = clean_string(
            record.get("nationality")
        ).upper()

        if not player_id or not nationality:
            continue

        lookup[player_id] = {
            "code": nationality,
            "source": "UEFA squad page",
            "source_team_id": clean_string(
                record.get("team_id")
            ),
            "source_team_code": clean_string(
                record.get("team_code")
            ),
        }

    if lookup:
        print(
            "Loaded "
            f"{len(lookup)} existing nationality "
            "records as fallback."
        )

    return lookup


def fetch_nationality_data(
    teams: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    Nationality is enrichment, not a dependency.

    If one UEFA squad page times out, the core fantasy
    update still completes.
    """

    lookup = (
        load_existing_nationality_lookup()
    )

    fresh_records: list[
        dict[str, Any]
    ] = []

    failed_teams: list[str] = []

    for team in teams:
        team_id = clean_string(
            team.get("id")
        )

        team_name = clean_string(
            team.get("name")
        )

        team_code = clean_string(
            team.get("code")
        )

        if not team_id:
            continue

        url = (
            f"{UEFA_SQUAD_BASE}/"
            f"{team_id}/squad/"
        )

        html = fetch_optional_text(url)

        if html is None:
            failed_teams.append(
                team_code or team_name
            )
            continue

        write_text(
            SQUAD_RAW_DIR
            / f"{team_code or team_id}.html",
            html,
        )

        records = (
            parse_squad_nationalities(
                html=html,
                team_id=team_id,
                team_name=team_name,
                team_code=team_code,
            )
        )

        print(
            f"  {team_code}: "
            f"{len(records)} "
            "nationality records"
        )

        fresh_records.extend(records)

        for record in records:
            player_id = (
                record["player_id"]
            )

            new_code = (
                record["nationality"]
            )

            existing = lookup.get(
                player_id
            )

            if (
                existing
                and existing["code"]
                != new_code
            ):
                print(
                    "WARNING: nationality changed "
                    f"for {player_id}: "
                    f"{existing['code']} -> "
                    f"{new_code}"
                )

            lookup[player_id] = {
                "code": new_code,
                "source": "UEFA squad page",
                "source_team_id":
                    record["team_id"],
                "source_team_code":
                    record["team_code"],
            }

    if failed_teams:
        print()
        print(
            "WARNING: squad pages failed for: "
            + ", ".join(failed_teams)
        )
        print(
            "Existing nationality data was "
            "retained where available."
        )

    # Build an output record from the merged lookup so a
    # temporary page failure never deletes known nationality.
    merged_records: list[
        dict[str, Any]
    ] = []

    fresh_by_id = {
        r["player_id"]: r
        for r in fresh_records
    }

    for player_id, info in lookup.items():
        if player_id in fresh_by_id:
            merged_records.append(
                fresh_by_id[player_id]
            )
            continue

        merged_records.append(
            {
                "player_id": player_id,
                "name": "",
                "nationality":
                    info["code"],
                "team_id":
                    info.get(
                        "source_team_id",
                        "",
                    ),
                "team": "",
                "team_code":
                    info.get(
                        "source_team_code",
                        "",
                    ),
            }
        )

    merged_records.sort(
        key=lambda record: (
            record["nationality"],
            record["name"],
            record["player_id"],
        )
    )

    return lookup, merged_records


# ============================================================
# PLAYER NORMALIZATION
# ============================================================

def normalize_player(
    player: dict[str, Any],
    nationality_lookup: dict[
        str,
        dict[str, Any],
    ],
) -> dict[str, Any]:
    player_id = clean_string(
        player.get("id")
    )

    skill = unwrap_number(
        player.get("skill"),
        None,
    )

    try:
        skill_int = int(skill)
    except (TypeError, ValueError):
        skill_int = None

    nationality = (
        nationality_lookup.get(
            player_id
        )
    )

    upcoming = (
        player.get(
            "upcomingMatchesList"
        )
        or []
    )

    current_matches = (
        player.get(
            "currentMatchesList"
        )
        or []
    )

    next_match = (
        normalize_match_reference(
            upcoming[0]
        )
        if upcoming
        else None
    )

    current_match = (
        normalize_match_reference(
            current_matches[0]
        )
        if current_matches
        else None
    )

    return {
        "id": player_id,

        "name": clean_string(
            player.get("pFName")
            or player.get("latinName")
            or player.get("pDName")
        ),

        "display_name": clean_string(
            player.get("pDName")
        ),

        "latin_name": clean_string(
            player.get("latinName")
        ),

        "nationality": {
            "code": (
                nationality["code"]
                if nationality
                else ""
            ),
            "source": (
                nationality["source"]
                if nationality
                else ""
            ),
        },

        "team": {
            "id": clean_string(
                player.get("tId")
            ),
            "name": clean_string(
                player.get("tName")
            ),
            "code": clean_string(
                player.get("cCode")
            ),
        },

        "position": POSITION_MAP.get(
            skill_int,
            (
                f"UNKNOWN_{skill_int}"
                if skill_int is not None
                else "UNKNOWN"
            ),
        ),

        "position_id": skill_int,

        "price": unwrap_number(
            player.get("value"),
            None,
        ),

        "selected_pct": unwrap_number(
            player.get("selPer"),
            0,
        ),

        "transfer_activity": {
            "transfers_in":
                unwrap_number(
                    player.get(
                        "mTransferIn"
                    ),
                    0,
                ),
            "transfers_out":
                unwrap_number(
                    player.get(
                        "mTransferOut"
                    ),
                    0,
                ),
            "selected_in_pct":
                unwrap_number(
                    player.get(
                        "selInPer"
                    ),
                    0,
                ),
            "selected_out_pct":
                unwrap_number(
                    player.get(
                        "selOutPer"
                    ),
                    0,
                ),
        },

        "active": bool(
            unwrap_number(
                player.get("isActive"),
                0,
            )
        ),

        "status":
            normalize_status(player),

        "historical_stats": {
            "season":
                HISTORICAL_STATS_SEASON,

            "minutes":
                unwrap_number(
                    player.get(
                        "minsPlyd"
                    ),
                    0,
                ),

            "fantasy_points":
                unwrap_number(
                    player.get(
                        "totPts"
                    ),
                    0,
                ),

            "goals":
                unwrap_number(
                    player.get("gS"),
                    0,
                ),

            "assists":
                unwrap_number(
                    player.get(
                        "assist"
                    ),
                    0,
                ),

            "clean_sheets":
                unwrap_number(
                    player.get("cS"),
                    0,
                ),

            "goals_conceded":
                unwrap_number(
                    player.get("gC"),
                    0,
                ),

            "yellow_cards":
                unwrap_number(
                    player.get("yC"),
                    0,
                ),

            "red_cards":
                unwrap_number(
                    player.get("rC"),
                    0,
                ),

            "own_goals":
                unwrap_number(
                    player.get("oG"),
                    0,
                ),

            "penalties_saved":
                unwrap_number(
                    player.get("pS"),
                    0,
                ),

            "penalties_conceded":
                unwrap_number(
                    player.get("pC"),
                    0,
                ),

            "penalties_earned":
                unwrap_number(
                    player.get("pE"),
                    0,
                ),

            "saves":
                unwrap_number(
                    player.get("saves"),
                    0,
                ),

            "penalty_misses":
                unwrap_number(
                    player.get("pM"),
                    0,
                ),

            "ball_recoveries":
                unwrap_number(
                    player.get("bR"),
                    0,
                ),

            "goals_outside_box":
                unwrap_number(
                    player.get("gOB"),
                    0,
                ),

            "player_of_match_awards":
                unwrap_number(
                    player.get("mOM"),
                    0,
                ),

            "player_of_match_points":
                unwrap_number(
                    player.get(
                        "mOMPts"
                    ),
                    0,
                ),
        },

        "current_matchday": {
            "matchday":
                clean_string(
                    player.get("mdId")
                ),

            "points":
                unwrap_number(
                    player.get(
                        "curGDPts"
                    ),
                    0,
                ),

            "played":
                bool(
                    unwrap_number(
                        player.get(
                            "isPlayed"
                        ),
                        0,
                    )
                ),

            "current_match":
                current_match,

            "next_match":
                next_match,
        },

        "uefa_categories": {
            f"category{i}":
                unwrap_number(
                    player.get(
                        f"category{i}"
                    ),
                    0,
                )
            for i in range(1, 16)
        },

        "uefa_extra": {
            "rating":
                unwrap_number(
                    player.get(
                        "rating"
                    ),
                    0,
                ),

            "avg_player_points":
                unwrap_number(
                    player.get(
                        "avgPlayerPts"
                    ),
                    0,
                ),

            "avg_player_value":
                unwrap_number(
                    player.get(
                        "avgPlayerValue"
                    ),
                    0,
                ),

            "last_gameday_points":
                unwrap_number(
                    player.get(
                        "lastGdPoints"
                    ),
                    0,
                ),

            "daily_total_points":
                unwrap_number(
                    player.get(
                        "dTotPts"
                    ),
                    0,
                ),

            "pot_id":
                clean_string(
                    player.get("ptId")
                ),

            "pot_name":
                clean_string(
                    player.get("ptName")
                ),
        },
    }


def normalize_players(
    payload: dict[str, Any],
    nationality_lookup: dict[
        str,
        dict[str, Any],
    ],
) -> list[dict[str, Any]]:
    player_list = (
        payload
        .get("data", {})
        .get("value", {})
        .get("playerList", [])
    )

    if not isinstance(
        player_list,
        list,
    ):
        raise ValueError(
            "Could not locate "
            "data.value.playerList "
            "in UEFA players feed"
        )

    normalized = [
        normalize_player(
            player,
            nationality_lookup,
        )
        for player in player_list
        if isinstance(player, dict)
    ]

    normalized.sort(
        key=lambda p: (
            p["team"]["name"],
            p["position"],
            p["name"],
        )
    )

    return normalized


# ============================================================
# FIXTURE NORMALIZATION
# ============================================================

def normalize_fixture_match(
    matchday_id: Any,
    match: dict[str, Any],
) -> dict[str, Any]:
    return {
        "match_id":
            clean_string(
                match.get("mId")
            ),

        "matchday":
            int(matchday_id),

        "fantasy_gameday_id":
            clean_string(
                match.get("gdId")
            ),

        "kickoff":
            clean_string(
                match.get(
                    "dateTime"
                )
            ),

        "lock_time":
            clean_string(
                match.get(
                    "dateTimeLock"
                )
            ),

        "home": {
            "id":
                clean_string(
                    match.get(
                        "htId"
                    )
                ),
            "name":
                clean_string(
                    match.get(
                        "htName"
                    )
                ),
            "code":
                clean_string(
                    match.get(
                        "htCCode"
                    )
                ),
            "score":
                clean_string(
                    match.get(
                        "htScore"
                    )
                ),
        },

        "away": {
            "id":
                clean_string(
                    match.get(
                        "atId"
                    )
                ),
            "name":
                clean_string(
                    match.get(
                        "atName"
                    )
                ),
            "code":
                clean_string(
                    match.get(
                        "atCCode"
                    )
                ),
            "score":
                clean_string(
                    match.get(
                        "atScore"
                    )
                ),
        },

        "status":
            clean_string(
                match.get(
                    "matchStatus"
                )
            ),

        "is_live":
            bool(
                unwrap_number(
                    match.get(
                        "isLive"
                    ),
                    0,
                )
            ),

        "feed_live":
            str(
                match.get(
                    "isFeedLive",
                    "0",
                )
            ) == "1",

        "locked":
            bool(
                unwrap_number(
                    match.get(
                        "gmIsLocked"
                    ),
                    0,
                )
            ),

        "postponed":
            bool(
                unwrap_number(
                    match.get(
                        "isMatchPostponed"
                    ),
                    0,
                )
            ),

        "lineup_announced":
            bool(
                unwrap_number(
                    match.get(
                        "lineupAnnounced"
                    ),
                    0,
                )
            ),

        "venue": {
            "stadium_id":
                clean_string(
                    match.get(
                        "stadiumId"
                    )
                ),

            "stadium":
                clean_string(
                    match.get(
                        "stadiumName"
                    )
                ),

            "city":
                clean_string(
                    match.get(
                        "venueName"
                    )
                ),

            "country_code":
                clean_string(
                    match.get(
                        "venueCountryCode"
                    )
                ),
        },
    }


def normalize_fixtures(
    payload: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    matchdays = (
        payload
        .get("data", {})
        .get("value", [])
    )

    if not isinstance(
        matchdays,
        list,
    ):
        raise ValueError(
            "Could not locate "
            "data.value in UEFA "
            "fixtures feed"
        )

    normalized_matchdays = []
    normalized_matches = []

    for matchday in matchdays:
        if not isinstance(
            matchday,
            dict,
        ):
            continue

        md_id = matchday.get("mdId")

        md_record = {
            "matchday":
                md_id,

            "phase_id":
                matchday.get(
                    "phId"
                ),

            "deadline":
                clean_string(
                    matchday.get(
                        "deadline"
                    )
                ),

            "is_current":
                bool(
                    unwrap_number(
                        matchday.get(
                            "mdIsCurrent"
                        ),
                        0,
                    )
                ),

            "is_locked":
                bool(
                    unwrap_number(
                        matchday.get(
                            "mdIsLocked"
                        ),
                        0,
                    )
                ),

            "fantasy_gameday_current":
                bool(
                    unwrap_number(
                        matchday.get(
                            "gdIsCurrent"
                        ),
                        0,
                    )
                ),

            "fantasy_gameday_locked":
                bool(
                    unwrap_number(
                        matchday.get(
                            "gdIsLocked"
                        ),
                        0,
                    )
                ),

            "subs_allowed":
                unwrap_number(
                    matchday.get(
                        "subsAllowed"
                    ),
                    0,
                ),

            "match_ids": [],
        }

        matches = (
            matchday.get("match")
            or []
        )

        for match in matches:
            if not isinstance(
                match,
                dict,
            ):
                continue

            normalized = (
                normalize_fixture_match(
                    md_id,
                    match,
                )
            )

            normalized_matches.append(
                normalized
            )

            md_record[
                "match_ids"
            ].append(
                normalized[
                    "match_id"
                ]
            )

        normalized_matchdays.append(
            md_record
        )

    normalized_matches.sort(
        key=lambda match: (
            match["matchday"],
            match["kickoff"],
            match["match_id"],
        )
    )

    normalized_matchdays.sort(
        key=lambda md:
            md["matchday"]
    )

    return (
        normalized_matchdays,
        normalized_matches,
    )


# ============================================================
# ARCHIVE
# ============================================================

def save_preseason_snapshot(
    raw_payloads: dict[
        str,
        dict[str, Any],
    ],
) -> bool:
    marker = (
        PRESEASON_ARCHIVE_DIR
        / "_ARCHIVED.txt"
    )

    if marker.exists():
        print(
            "Preseason archive already exists; "
            "leaving it untouched."
        )

        return False

    print(
        "Creating permanent 2026-09-21 "
        "preseason archive..."
    )

    for name, payload in (
        raw_payloads.items()
    ):
        write_json(
            PRESEASON_ARCHIVE_DIR
            / f"{name}_raw.json",
            payload,
        )

    marker.write_text(
        (
            "Permanent preseason snapshot "
            "of UEFA UWCL Fantasy feeds.\n"
            "Captured before the first "
            "2026/27 league-phase matches.\n"
            "Player statistical totals "
            "appear to contain "
            "carried-forward 2025/26 "
            "UWCL data.\n"
            "DO NOT OVERWRITE THESE FILES.\n"
        ),
        encoding="utf-8",
    )

    return True


def save_preseason_nationalities(
    squad_records: list[
        dict[str, Any]
    ],
) -> bool:
    path = (
        PRESEASON_ARCHIVE_DIR
        / "nationalities.json"
    )

    if path.exists():
        print(
            "Preseason nationality snapshot "
            "already exists; leaving untouched."
        )

        return False

    write_json(
        path,
        {
            "competition":
                "UWCL",

            "season":
                CURRENT_SEASON,

            "source":
                "UEFA squad pages",

            "captured_at_utc":
                utc_now_iso(),

            "count":
                len(squad_records),

            "players":
                squad_records,
        },
    )

    print(
        "Saved permanent preseason "
        "nationality snapshot."
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    ensure_dirs()

    fetched_at = utc_now_iso()

    raw_payloads: dict[
        str,
        dict[str, Any],
    ] = {}

    # Core fantasy feeds are required.
    # Each now gets up to five attempts and a 120s read timeout.
    for name, url in URLS.items():
        raw_payloads[name] = (
            fetch_json(url)
        )

        write_json(
            RAW_DIR
            / f"{name}_raw.json",
            raw_payloads[name],
        )

    archived_now = (
        save_preseason_snapshot(
            raw_payloads
        )
    )

    teams = normalize_teams(
        raw_payloads["teams"]
    )

    # Squad pages are optional enrichment.
    nationality_lookup, squad_records = (
        fetch_nationality_data(
            teams
        )
    )

    nationality_archive_created = (
        save_preseason_nationalities(
            squad_records
        )
    )

    players = normalize_players(
        raw_payloads["players"],
        nationality_lookup,
    )

    matchdays, matches = (
        normalize_fixtures(
            raw_payloads["fixtures"]
        )
    )

    current_matchday = next(
        (
            md["matchday"]
            for md in matchdays
            if md["is_current"]
        ),
        None,
    )

    matched_nationalities = sum(
        1
        for player in players
        if player["nationality"]["code"]
    )

    unmatched_players = [
        {
            "id":
                player["id"],

            "name":
                player["name"],

            "team":
                player["team"]["name"],

            "team_code":
                player["team"]["code"],

            "position":
                player["position"],
        }
        for player in players
        if not player[
            "nationality"
        ]["code"]
    ]

    nationality_codes = sorted(
        {
            player[
                "nationality"
            ]["code"]
            for player in players
            if player[
                "nationality"
            ]["code"]
        }
    )

    write_json(
        DATA_DIR / "players.json",
        {
            "competition":
                "UWCL",

            "season":
                CURRENT_SEASON,

            "count":
                len(players),

            "players":
                players,
        },
    )

    write_json(
        DATA_DIR / "teams.json",
        {
            "competition":
                "UWCL",

            "season":
                CURRENT_SEASON,

            "count":
                len(teams),

            "teams":
                teams,
        },
    )

    write_json(
        DATA_DIR / "fixtures.json",
        {
            "competition":
                "UWCL",

            "season":
                CURRENT_SEASON,

            "matchdays":
                matchdays,

            "matches":
                matches,
        },
    )

    write_json(
        DATA_DIR / "nationalities.json",
        {
            "competition":
                "UWCL",

            "season":
                CURRENT_SEASON,

            "source":
                "UEFA squad pages",

            "fetched_at_utc":
                fetched_at,

            "matched_players":
                matched_nationalities,

            "fantasy_players":
                len(players),

            "unmatched_players":
                len(
                    unmatched_players
                ),

            "nationality_count":
                len(
                    nationality_codes
                ),

            "nationalities":
                nationality_codes,

            "players":
                squad_records,

            "unmatched_fantasy_players":
                unmatched_players,
        },
    )

    metadata = {
        "competition":
            "UWCL",

        "season":
            CURRENT_SEASON,

        "current_matchday":
            current_matchday,

        "historical_stats": {
            "season":
                HISTORICAL_STATS_SEASON,

            "status":
                (
                    "preseason_carried_"
                    "forward_unverified"
                ),

            "note":
                (
                    "Before the first "
                    "2026/27 matches, "
                    "UEFA's player feed "
                    "contains non-zero "
                    "totals that appear "
                    "to be carried "
                    "forward from "
                    "2025/26. The "
                    "permanent preseason "
                    "raw snapshot is "
                    "retained for "
                    "comparison after "
                    "UEFA updates the "
                    "feed."
                ),
        },

        "nationality_data": {
            "source":
                (
                    "UEFA Women's "
                    "Champions League "
                    "squad pages"
                ),

            "join_key":
                "UEFA player ID",

            "matched_players":
                matched_nationalities,

            "unmatched_players":
                len(
                    unmatched_players
                ),

            "nationality_count":
                len(
                    nationality_codes
                ),

            "preseason_archive_created":
                nationality_archive_created,
        },

        "counts": {
            "players":
                len(players),

            "teams":
                len(teams),

            "matches":
                len(matches),

            "matchdays":
                len(matchdays),
        },

        "sources": {
            **deepcopy(URLS),

            "squads":
                (
                    f"{UEFA_SQUAD_BASE}"
                    "/{team_id}/squad/"
                ),
        },

        "fetched_at_utc":
            fetched_at,

        "preseason_archive": {
            "path":
                str(
                    PRESEASON_ARCHIVE_DIR
                ),

            "created_this_run":
                archived_now,
        },
    }

    write_json(
        DATA_DIR / "meta.json",
        metadata,
    )

    print()
    print("UWCL fetch complete.")
    print(
        f"Players: {len(players)}"
    )
    print(
        f"Teams: {len(teams)}"
    )
    print(
        f"Matches: {len(matches)}"
    )
    print(
        f"Matchdays: {len(matchdays)}"
    )
    print(
        "Current matchday: "
        f"{current_matchday}"
    )
    print(
        "Nationality matches: "
        f"{matched_nationalities}"
        f"/{len(players)}"
    )
    print(
        "Nationality codes: "
        f"{len(nationality_codes)}"
    )
    print(
        "Unmatched players: "
        f"{len(unmatched_players)}"
    )
    print(
        f"Fetched at: {fetched_at}"
    )

    if unmatched_players:
        print()
        print(
            "First players without "
            "nationality:"
        )

        for player in (
            unmatched_players[:30]
        ):
            print(
                "  "
                f"{player['team_code']} | "
                f"{player['name']} | "
                f"{player['id']}"
            )

        if len(
            unmatched_players
        ) > 30:
            print(
                "  ... plus "
                f"{len(unmatched_players) - 30} "
                "more"
            )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        raise
