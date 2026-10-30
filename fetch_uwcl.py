#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import requests


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://gaming.uefa.com/en/uwclfantasy/services/feeds"

URLS = {
    "players": None,  # resolved from live fixtures matchday
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

# The GitHub Actions diagnostic on 2026-10-29 confirmed that UEFA responds
# immediately to a minimal User-Agent and curl, but times out for browser headers.
REQUEST_HEADERS = {"User-Agent": "UWCL-Diagnostic/1.0"}
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 8
MAX_ATTEMPTS = 1

SESSION = requests.Session()
SESSION.headers.clear()
SESSION.headers.update(REQUEST_HEADERS)


def fetch_with_curl(url: str) -> Any:
    """Fallback transport; only return validated JSON, never an error page."""
    result = subprocess.run(
        ["curl", "-4", "--http1.1", "--location", "--fail", "--silent",
         "--show-error", "--max-time", "12", "--connect-timeout", "5",
         "--header", "User-Agent: UWCL-Diagnostic/1.0", url],
        capture_output=True, text=True, timeout=15, check=True,
    )
    return json.loads(result.stdout)


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

def validate_feed_payload(
    name: str,
    payload: dict[str, Any],
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(
            f"{name} feed was not a JSON object"
        )

    meta = payload.get("meta")
    if (
        isinstance(meta, dict)
        and meta.get("success") is False
    ):
        raise RuntimeError(
            f"{name} feed reported failure: {meta}"
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(
            f"{name} feed is missing data object"
        )

    value = data.get("value")

    if name == "players":
        player_list = (
            value.get("playerList", [])
            if isinstance(value, dict)
            else []
        )
        if not isinstance(player_list, list) or len(player_list) < 500:
            raise ValueError(
                f"players feed failed sanity check "
                f"({len(player_list) if isinstance(player_list, list) else 0} players)"
            )

    elif name == "teams":
        if not isinstance(value, list) or len(value) < 18:
            raise ValueError(
                f"teams feed failed sanity check "
                f"({len(value) if isinstance(value, list) else 0} teams)"
            )

    elif name == "fixtures":
        if not isinstance(value, list) or len(value) < 6:
            raise ValueError(
                f"fixtures feed failed sanity check "
                f"({len(value) if isinstance(value, list) else 0} matchdays)"
            )


def load_cached_feed(
    name: str,
) -> dict[str, Any] | None:
    path = RAW_DIR / f"{name}_raw.json"

    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
        validate_feed_payload(name, payload)
        return payload
    except Exception as exc:
        print(
            f"WARNING: cached {name} feed is unusable: {exc}",
            flush=True,
        )
        return None


def fetch_json(
    name: str,
    url: str,
) -> tuple[dict[str, Any], bool]:
    """
    Return (payload, fetched_live).

    We try UEFA briefly. If GitHub's runner cannot read the endpoint,
    we use the last committed raw feed so the scheduled workflow does
    not spend many minutes timing out or destroy last-known-good data.
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(
                f"Fetching {name}: {url} "
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
            validate_feed_payload(name, payload)

            print(
                f"Live {name} feed received successfully.",
                flush=True,
            )
            return payload, True

        except (
            requests.exceptions.RequestException,
            ValueError,
            RuntimeError,
        ) as exc:
            last_error = exc
            print(
                f"WARNING: live {name} attempt {attempt} failed: {exc}",
                flush=True,
            )

            if attempt < MAX_ATTEMPTS:
                time.sleep(2)

    try:
        print(f"Trying curl fallback for {name}...", flush=True)
        payload = fetch_with_curl(url)
        validate_feed_payload(name, payload)
        print(f"Live {name} feed received via curl.", flush=True)
        return payload, True
    except (subprocess.SubprocessError, ValueError, RuntimeError, OSError) as exc:
        print(f"WARNING: curl fallback for {name} failed: {exc}", flush=True)

    cached = load_cached_feed(name)

    if cached is not None:
        print(
            f"WARNING: using last-known-good cached {name} feed "
            f"from {RAW_DIR / f'{name}_raw.json'}.",
            flush=True,
        )
        return cached, False

    raise RuntimeError(
        f"Could not fetch {name} live and no usable cached feed exists: {url}"
    ) from last_error


# ============================================================
# NATIONALITY MASTER
# ============================================================

def load_nationality_lookup(
) -> dict[str, dict[str, str]]:
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

    lookup: dict[str, dict[str, str]] = {}

    for record in payload.get("players", []):
        if not isinstance(record, dict):
            continue

        player_id = clean_string(
            record.get("player_id")
        )
        nationality = clean_string(
            record.get("nationality")
        ).upper()
        source = clean_string(
            record.get("source")
        )

        if player_id and nationality:
            lookup[player_id] = {
                "code": nationality,
                "source": (
                    source
                    or "UEFA squad page"
                ),
            }

    print(
        f"Loaded {len(lookup)} nationality records "
        "from the local master file.",
        flush=True,
    )

    return lookup


# ============================================================
# MATCH REFERENCE
# ============================================================

def match_weekday(value: Any) -> str:
    if not value:
        return ""
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).strftime("%a").upper()
        except ValueError:
            continue
    return ""


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
        "kickoff": clean_string(match.get("matchDate")),
        "weekday": match_weekday(match.get("matchDate")),
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
        dict[str, str],
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

    nationality_record = (
        nationality_lookup.get(
            player_id,
            {},
        )
    )

    nationality = clean_string(
        nationality_record.get("code")
    )
    nationality_source = clean_string(
        nationality_record.get("source")
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
                nationality_source
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
            "season": CURRENT_SEASON,

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
        dict[str, str],
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

        "kickoff": clean_string(match.get("dateTime")),
        "weekday": match_weekday(match.get("dateTime")),

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
    feed_status = {}

    # The fixtures endpoint is stable, but may be inaccessible from GitHub.
    # Player feeds are matchday-specific: players_40_en_1.json, ..._6.json.
    # Use the published fixture deadlines to select the appropriate suffix,
    # even if the cached fixtures still say MD1 is current.
    fixtures_payload, fixtures_live = fetch_json("fixtures", URLS["fixtures"])
    if not fixtures_live:
        print("WARNING: live fixtures unavailable; using cached schedule "
              "ONLY to identify the matchday (not as fresh results).", flush=True)

    fixture_days = fixtures_payload["data"]["value"]
    if not isinstance(fixture_days, list) or len(fixture_days) < 6:
        raise RuntimeError("No valid fixtures schedule available")

    def matchday_from_schedule(days):
        now = datetime.now(ZoneInfo("Europe/Paris"))
        deadlines = []
        for day in days:
            try:
                deadline = datetime.strptime(day["deadline"], "%m/%d/%y %I:%M:%S %p")
                deadline = deadline.replace(tzinfo=ZoneInfo("Europe/Paris"))
                deadlines.append((deadline, int(day["mdId"])))
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Invalid fixture deadline: {day!r}: {exc}") from exc
        deadlines.sort()
        passed = [md for deadline, md in deadlines if deadline <= now]
        return passed[-1] if passed else deadlines[0][1]

    schedule_md = matchday_from_schedule(fixture_days)
    current_days = [d for d in fixture_days
                    if int(unwrap_number(d.get("mdIsCurrent"), 0)) == 1]
    live_md = int(current_days[0]["mdId"]) if len(current_days) == 1 else None
    # UEFA may mark the next round current ahead of its deadline. Trust live
    # metadata when present; never trust a stale cached mdIsCurrent flag.
    md = live_md if fixtures_live and live_md is not None else schedule_md
    if not 1 <= md <= 6:
        raise RuntimeError(f"Unexpected matchday: {md}")
    print(f"Selected matchday {md} (schedule={schedule_md}, "
          f"live fixture marker={live_md}, fixtures_live={fixtures_live})", flush=True)

    # When fixtures are cached, probe only the scheduled MD (and the previous
    # MD as a fallback near a rollover). Never accept an arbitrary future feed.
    candidate_mds = [md] if fixtures_live else list(dict.fromkeys([md, max(1, md - 1)]))
    players_payload = None
    for candidate in candidate_mds:
        player_url = f"{BASE_URL}/players/players_40_en_{candidate}.json"
        candidate_payload, candidate_live = fetch_json("players", player_url)
        if not candidate_live:
            continue
        records = candidate_payload["data"]["value"]["playerList"]
        md_values = {str(p.get("mdId")) for p in records}
        if md_values != {str(candidate)}:
            print(f"WARNING: player feed {candidate} has unexpected mdIds "
                  f"{md_values}; skipping", flush=True)
            continue
        if candidate != md:
            # Do not publish previous-round data as if it were current.
            print(f"WARNING: MD{md} unavailable; MD{candidate} is live, "
                  "but refusing to publish stale player data.", flush=True)
            break
        players_payload = candidate_payload
        break
    if players_payload is None:
        raise RuntimeError(f"Live player feed for MD{md} unavailable; "
                           "preserving last-known-good data")

    teams_payload, teams_live = fetch_json("teams", URLS["teams"])
    if not teams_live:
        # Team metadata is stable; cached team identities can safely be used
        # with fresh MD player data, unlike cached player points.
        print("WARNING: using cached teams metadata", flush=True)

    # Copy fixtures so we can correct an obsolete MD1 marker without changing
    # the committed raw cached schedule. This also drives meta.current_matchday.
    normalized_fixtures_payload = deepcopy(fixtures_payload)
    for day in normalized_fixtures_payload["data"]["value"]:
        day["mdIsCurrent"] = 1 if int(day["mdId"]) == md else 0

    raw_payloads = {
        "fixtures": normalized_fixtures_payload,
        "teams": teams_payload,
        "players": players_payload,
    }
    feed_status = {
        "fixtures": "live" if fixtures_live else "cached_schedule_with_corrected_matchday",
        "teams": "live" if teams_live else "cached_metadata",
        "players": f"live_md{md}",
    }
    # Preserve matchday-specific fantasy scores independently of the active feed.
    # Once a round is over, fetch its final scores once and keep them across
    # subsequent matchday transitions. Never overwrite a saved round with zeros.
    history_path = DATA_DIR / "matchday_points.json"
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    else:
        history = {"season": CURRENT_SEASON, "points_by_matchday": {}}
    by_md = history.setdefault("points_by_matchday", {})
    for past_md in range(1, md):
        key = str(past_md)
        if key in by_md and len(by_md[key]) >= 500:
            continue
        past_url = f"{BASE_URL}/players/players_40_en_{past_md}.json"
        try:
            past_payload, is_live = fetch_json("players", past_url)
            if not is_live:
                print(f"WARNING: historical MD{past_md} feed unavailable; keeping saved scores", flush=True)
                continue
            past_records = past_payload["data"]["value"]["playerList"]
            if {str(p.get("mdId")) for p in past_records} != {key} or len(past_records) < 500:
                print(f"WARNING: historical MD{past_md} feed invalid; keeping saved scores", flush=True)
                continue
            by_md[key] = {str(p["id"]): p.get("curGDPts", 0) for p in past_records}
        except Exception as exc:
            print(f"WARNING: unable to retrieve historical MD{past_md}: {exc}", flush=True)
    # Capture active round as well; it may still be in progress.
    current_records = players_payload["data"]["value"]["playerList"]
    by_md[str(md)] = {str(p["id"]): p.get("curGDPts", 0) for p in current_records}
    history["season"] = CURRENT_SEASON
    write_json(history_path, history)

    # All validation and live-player checks finish BEFORE writing raw files.
    write_json(RAW_DIR / "players_raw.json", players_payload)
    if teams_live:
        write_json(RAW_DIR / "teams_raw.json", teams_payload)
    if fixtures_live:
        write_json(RAW_DIR / "fixtures_raw.json", fixtures_payload)

    # Preserve the pre-existing preseason archive; never create one from
    # live matchday data after the season has started.
    archived_now = False

    nationality_lookup = (
        load_nationality_lookup()
    )

    players = normalize_players(
        raw_payloads["players"],
        nationality_lookup,
    )

    # Add per-round scores without changing existing player fields.
    for player in players:
        pid = str(player["id"])
        player["matchday_points"] = {
            round_id: points[pid]
            for round_id, points in by_md.items()
            if pid in points
        }

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

    active_players = [
        player
        for player in players
        if player["active"]
    ]

    active_nationality_matches = sum(
        1
        for player in active_players
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
            "season": CURRENT_SEASON,

            "status":
                "live_current_season",
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

            "active_players":
                len(active_players),

            "active_matched_players":
                active_nationality_matches,

            "active_unmatched_players":
                (
                    len(active_players)
                    - active_nationality_matches
                ),
        },

        "feed_status":
            deepcopy(feed_status),

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
    print(
        f"Active-player nationality matches: "
        f"{active_nationality_matches}/"
        f"{len(active_players)}",
        flush=True,
    )
    print(
        "Feed status: "
        + ", ".join(
            f"{name}={status}"
            for name, status
            in feed_status.items()
        ),
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
