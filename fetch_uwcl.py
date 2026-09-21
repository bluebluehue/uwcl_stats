#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://gaming.uefa.com/en/uwclfantasy/services/feeds"

URLS = {
    "players": f"{BASE_URL}/players/players_40_en_1.json",
    "teams": f"{BASE_URL}/teams/teams_40_en.json",
    "fixtures": f"{BASE_URL}/fixtures/fixtures_40_en.json",
}

DATA_DIR = Path("data/uwcl")
RAW_DIR = DATA_DIR / "raw"

PRESEASON_ARCHIVE_DIR = (
    DATA_DIR / "archive" / "2026-09-21-preseason"
)

NATIONALITY_MASTER_PATH = (
    DATA_DIR / "nationalities_master.json"
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
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 45
MAX_ATTEMPTS = 3

SESSION = requests.Session()
SESSION.headers.update(REQUEST_HEADERS)


# ============================================================
# HELPERS
# ============================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
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
        )
        handle.write("\n")


def clean_string(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def unwrap_number(
    value: Any,
    default: float | int | None = 0,
) -> Any:
    if isinstance(value, dict):
        if "parsedValue" in value:
            return value["parsedValue"]

        if "source" in value:
            try:
                return float(value["source"])
            except (TypeError, ValueError):
                return default

    if value is None:
        return default

    return value


# ============================================================
# HTTP
# ============================================================

def fetch_json(
    url: str,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1,
    ):
        try:
            print(
                f"Fetching {url} "
                f"(attempt {attempt}/{MAX_ATTEMPTS})",
                flush=True,
            )

            response = SESSION.get(
                url,
                timeout=(
                    CONNECT_TIMEOUT,
                    READ_TIMEOUT,
                ),
            )

            response.raise_for_status()

            payload = response.json()

            if not isinstance(
                payload,
                dict,
            ):
                raise ValueError(
                    "UEFA response was not "
                    "a JSON object"
                )

            meta = payload.get("meta")

            if (
                isinstance(meta, dict)
                and meta.get("success")
                is False
            ):
                raise RuntimeError(
                    f"UEFA feed reported failure: "
                    f"{meta}"
                )

            return payload

        except (
            requests.exceptions.RequestException,
            ValueError,
        ) as exc:
            last_error = exc

            print(
                f"WARNING: attempt {attempt} failed: "
                f"{exc}",
                flush=True,
            )

            if attempt < MAX_ATTEMPTS:
                wait_seconds = attempt * 2

                print(
                    f"Retrying in "
                    f"{wait_seconds}s...",
                    flush=True,
                )

                time.sleep(wait_seconds)

    raise RuntimeError(
        f"Failed to fetch required URL after "
        f"{MAX_ATTEMPTS} attempts: {url}"
    ) from last_error


# ============================================================
# NATIONALITY MASTER
# ============================================================

def load_nationality_lookup(
) -> dict[str, str]:
    if not NATIONALITY_MASTER_PATH.exists():
        print(
            "No nationality master file yet; "
            "continuing without nationality data.",
            flush=True,
        )
        return {}

    try:
        payload = json.loads(
            NATIONALITY_MASTER_PATH.read_text(
                encoding="utf-8"
            )
        )
    except Exception as exc:
        print(
            "WARNING: could not read nationality "
            f"master file: {exc}",
            flush=True,
        )
        return {}

    lookup: dict[str, str] = {}

    for record in payload.get(
        "players",
        [],
    ):
        if not isinstance(
            record,
            dict,
        ):
            continue

        player_id = clean_string(
            record.get("player_id")
        )

        nationality = clean_string(
            record.get("nationality")
        ).upper()

        if player_id and nationality:
            lookup[player_id] = nationality

    print(
        f"Loaded {len(lookup)} nationality "
        "records.",
        flush=True,
    )

    return lookup


# ============================================================
# MATCH REFERENCE
# ============================================================

def normalize_match_reference(
    match: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(
        match,
        dict,
    ):
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
# PLAYER NORMALIZATION
# ============================================================

def normalize_status(
    player: dict[str, Any],
) -> dict[str, Any]:
    code = clean_string(
        player.get("pStatus")
    )

    labels = {
        "I": "Injured",
        "D": "Doubtful",
        "S": "Suspended",
    }

    return {
        "code": code,
        "label": labels.get(
            code,
            "",
        ),
        "availability_text": clean_string(
            player.get("trained")
        ),
    }


def normalize_player(
    player: dict[str, Any],
    nationality_lookup: dict[
        str,
        str,
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
        position_id = int(skill)
    except (TypeError, ValueError):
        position_id = None

    current_matches = (
        player.get(
            "currentMatchesList"
        )
        or []
    )

    upcoming_matches = (
        player.get(
            "upcomingMatchesList"
        )
        or []
    )

    nationality = (
        nationality_lookup.get(
            player_id,
            "",
        )
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
            "code": nationality,
            "source": (
                "UEFA squad page"
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
            position_id,
            (
                f"UNKNOWN_{position_id}"
                if position_id is not None
                else "UNKNOWN"
            ),
        ),

        "position_id": position_id,

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
                    player.get("minsPlyd"),
                    0,
                ),

            "fantasy_points":
                unwrap_number(
                    player.get("totPts"),
                    0,
                ),

            "goals":
                unwrap_number(
                    player.get("gS"),
                    0,
                ),

            "assists":
                unwrap_number(
                    player.get("assist"),
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
                    player.get("mOMPts"),
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
                normalize_match_reference(
                    current_matches[0]
                    if current_matches
                    else None
                ),

            "next_match":
                normalize_match_reference(
                    upcoming_matches[0]
                    if upcoming_matches
                    else None
                ),
        },

        "uefa_categories": {
            f"category{i}":
                unwrap_number(
                    player.get(
                        f"category{i}"
                    ),
                    0,
                )
            for i in range(
                1,
                16,
            )
        },

        "uefa_extra": {
            "rating":
                unwrap_number(
                    player.get("rating"),
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
        str,
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
            "data.value.playerList"
        )

    players = [
        normalize_player(
            player,
            nationality_lookup,
        )
        for player in player_list
        if isinstance(
            player,
            dict,
        )
    ]

    players.sort(
        key=lambda p: (
            p["team"]["name"],
            p["position"],
            p["name"],
        )
    )

    return players


# ============================================================
# TEAM NORMALIZATION
# ============================================================

def normalize_team(
    team: dict[str, Any],
) -> dict[str, Any]:
    upcoming = (
        team.get(
            "upcomingMatchesList"
        )
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

        "eliminated":
            team.get(
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

        "next_match":
            normalize_match_reference(
                upcoming[0]
                if upcoming
                else None
            ),
    }


def normalize_teams(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_teams = (
        payload
        .get("data", {})
        .get("value", [])
    )

    teams = [
        normalize_team(team)
        for team in raw_teams
        if isinstance(
            team,
            dict,
        )
    ]

    teams.sort(
        key=lambda team:
            team["name"]
    )

    return teams


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
                match.get("dateTime")
            ),

        "lock_time":
            clean_string(
                match.get("dateTimeLock")
            ),

        "home": {
            "id":
                clean_string(
                    match.get("htId")
                ),
            "name":
                clean_string(
                    match.get("htName")
                ),
            "code":
                clean_string(
                    match.get("htCCode")
                ),
            "score":
                clean_string(
                    match.get("htScore")
                ),
        },

        "away": {
            "id":
                clean_string(
                    match.get("atId")
                ),
            "name":
                clean_string(
                    match.get("atName")
                ),
            "code":
                clean_string(
                    match.get("atCCode")
                ),
            "score":
                clean_string(
                    match.get("atScore")
                ),
        },

        "status":
            clean_string(
                match.get("matchStatus")
            ),

        "is_live":
            bool(
                unwrap_number(
                    match.get("isLive"),
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
    raw_matchdays = (
        payload
        .get("data", {})
        .get("value", [])
    )

    matchdays = []
    matches = []

    for matchday in raw_matchdays:
        if not isinstance(
            matchday,
            dict,
        ):
            continue

        md_id = matchday.get(
            "mdId"
        )

        md = {
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

        for raw_match in (
            matchday.get("match")
            or []
        ):
            normalized = (
                normalize_fixture_match(
                    md_id,
                    raw_match,
                )
            )

            matches.append(
                normalized
            )

            md[
                "match_ids"
            ].append(
                normalized[
                    "match_id"
                ]
            )

        matchdays.append(md)

    matchdays.sort(
        key=lambda md:
            md["matchday"]
    )

    matches.sort(
        key=lambda m: (
            m["matchday"],
            m["kickoff"],
            m["match_id"],
        )
    )

    return matchdays, matches


# ============================================================
# PRESEASON ARCHIVE
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
            "leaving it untouched.",
            flush=True,
        )
        return False

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
            "Permanent preseason snapshot of UEFA UWCL "
            "Fantasy feeds.\n"
            "Captured before the first 2026/27 "
            "league-phase matches.\n"
            "DO NOT OVERWRITE THESE FILES.\n"
        ),
        encoding="utf-8",
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    ensure_dirs()

    fetched_at = utc_now_iso()

    raw_payloads = {}

    for name, url in URLS.items():
        payload = fetch_json(url)

        raw_payloads[name] = payload

        write_json(
            RAW_DIR
            / f"{name}_raw.json",
            payload,
        )

    archived_now = (
        save_preseason_snapshot(
            raw_payloads
        )
    )

    nationality_lookup = (
        load_nationality_lookup()
    )

    players = normalize_players(
        raw_payloads["players"],
        nationality_lookup,
    )

    teams = normalize_teams(
        raw_payloads["teams"]
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

    nationality_matches = sum(
        1
        for player in players
        if player[
            "nationality"
        ]["code"]
    )

    write_json(
        DATA_DIR / "players.json",
        {
            "competition": "UWCL",
            "season": CURRENT_SEASON,
            "count": len(players),
            "players": players,
        },
    )

    write_json(
        DATA_DIR / "teams.json",
        {
            "competition": "UWCL",
            "season": CURRENT_SEASON,
            "count": len(teams),
            "teams": teams,
        },
    )

    write_json(
        DATA_DIR / "fixtures.json",
        {
            "competition": "UWCL",
            "season": CURRENT_SEASON,
            "matchdays": matchdays,
            "matches": matches,
        },
    )

    meta = {
        "competition": "UWCL",

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
        },

        "nationality_data": {
            "source":
                (
                    "UEFA squad-page "
                    "reference file"
                ),

            "master_file":
                str(
                    NATIONALITY_MASTER_PATH
                ),

            "matched_players":
                nationality_matches,

            "unmatched_players":
                (
                    len(players)
                    - nationality_matches
                ),
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

        "sources":
            deepcopy(URLS),

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
        meta,
    )

    print()
    print(
        "UWCL fetch complete.",
        flush=True,
    )
    print(
        f"Players: {len(players)}",
        flush=True,
    )
    print(
        f"Teams: {len(teams)}",
        flush=True,
    )
    print(
        f"Matches: {len(matches)}",
        flush=True,
    )
    print(
        f"Matchdays: {len(matchdays)}",
        flush=True,
    )
    print(
        f"Nationality matches: "
        f"{nationality_matches}/"
        f"{len(players)}",
        flush=True,
    )

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
