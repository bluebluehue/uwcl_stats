#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
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

# Important:
# This snapshot is intentionally never overwritten.
# It preserves the feed as UEFA exposed it immediately before
# the first 2026/27 league-phase matches.
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
        "Mozilla/5.0 (compatible; UWCLFantasyDataFetcher/1.0)"
    ),
    "Accept": "application/json,text/plain,*/*",
}


# ============================================================
# HELPERS
# ============================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PRESEASON_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def fetch_json(url: str) -> dict[str, Any]:
    print(f"Fetching {url}")

    response = requests.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected top-level object from {url}, "
            f"got {type(payload).__name__}"
        )

    meta = payload.get("meta")

    if isinstance(meta, dict):
        success = meta.get("success")

        if success is False:
            raise RuntimeError(
                f"UEFA feed reported failure for {url}: {meta}"
            )

    return payload


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

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


def unwrap_number(
    value: Any,
    default: float | int | None = 0,
) -> Any:
    """
    UEFA inconsistently represents some numeric values as either:

        9.5

    or:

        {
          "source": "9.5",
          "parsedValue": 9.5
        }

    Normalize both forms.
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


def clean_string(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def normalize_status(player: dict[str, Any]) -> dict[str, Any]:
    code = clean_string(player.get("pStatus"))

    status_labels = {
        "I": "Injured",
        "D": "Doubtful",
        "S": "Suspended",
    }

    return {
        "code": code,
        "label": status_labels.get(code, ""),
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
        "matchday": clean_string(match.get("mdId")),
        "team_id": clean_string(match.get("tId")),
        "team": clean_string(match.get("tSCode")),
        "team_code": clean_string(match.get("cCode")),
        "home_away": clean_string(match.get("tLoc")),
        "opponent_id": clean_string(match.get("vsTID")),
        "opponent": clean_string(match.get("vsTSCode")),
        "opponent_code": clean_string(
            match.get("vsCCode")
        ),
        "opponent_home_away": clean_string(
            match.get("vsTLoc")
        ),
        "kickoff": clean_string(match.get("matchDate")),
    }


# ============================================================
# PLAYER NORMALIZATION
# ============================================================

def normalize_player(
    player: dict[str, Any],
) -> dict[str, Any]:
    skill = unwrap_number(player.get("skill"), None)

    try:
        skill_int = int(skill)
    except (TypeError, ValueError):
        skill_int = None

    upcoming = player.get("upcomingMatchesList") or []
    current_matches = player.get("currentMatchesList") or []

    next_match = (
        normalize_match_reference(upcoming[0])
        if upcoming
        else None
    )

    current_match = (
        normalize_match_reference(current_matches[0])
        if current_matches
        else None
    )

    status = normalize_status(player)

    return {
        "id": clean_string(player.get("id")),
        "name": clean_string(
            player.get("pFName")
            or player.get("latinName")
            or player.get("pDName")
        ),
        "display_name": clean_string(player.get("pDName")),
        "latin_name": clean_string(player.get("latinName")),

        "team": {
            "id": clean_string(player.get("tId")),
            "name": clean_string(player.get("tName")),
            "code": clean_string(player.get("cCode")),
        },

        "position": POSITION_MAP.get(
            skill_int,
            f"UNKNOWN_{skill_int}"
            if skill_int is not None
            else "UNKNOWN",
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
            "transfers_in": unwrap_number(
                player.get("mTransferIn"),
                0,
            ),
            "transfers_out": unwrap_number(
                player.get("mTransferOut"),
                0,
            ),
            "selected_in_pct": unwrap_number(
                player.get("selInPer"),
                0,
            ),
            "selected_out_pct": unwrap_number(
                player.get("selOutPer"),
                0,
            ),
        },

        "active": bool(
            unwrap_number(player.get("isActive"), 0)
        ),

        "status": status,

        # ----------------------------------------------------
        # HISTORICAL / CARRIED-FORWARD STATS
        #
        # Before MD1 of 2026/27 UEFA is visibly carrying
        # previous UWCL totals in these fields.
        #
        # We deliberately label these 2025/26 rather than
        # pretending they are current-season totals.
        # ----------------------------------------------------
        "historical_stats": {
            "season": HISTORICAL_STATS_SEASON,
            "minutes": unwrap_number(
                player.get("minsPlyd"),
                0,
            ),
            "fantasy_points": unwrap_number(
                player.get("totPts"),
                0,
            ),
            "goals": unwrap_number(
                player.get("gS"),
                0,
            ),
            "assists": unwrap_number(
                player.get("assist"),
                0,
            ),
            "clean_sheets": unwrap_number(
                player.get("cS"),
                0,
            ),
            "goals_conceded": unwrap_number(
                player.get("gC"),
                0,
            ),
            "yellow_cards": unwrap_number(
                player.get("yC"),
                0,
            ),
            "red_cards": unwrap_number(
                player.get("rC"),
                0,
            ),
            "own_goals": unwrap_number(
                player.get("oG"),
                0,
            ),
            "penalties_saved": unwrap_number(
                player.get("pS"),
                0,
            ),
            "penalties_conceded": unwrap_number(
                player.get("pC"),
                0,
            ),
            "penalties_earned": unwrap_number(
                player.get("pE"),
                0,
            ),
            "saves": unwrap_number(
                player.get("saves"),
                0,
            ),
            "penalty_misses": unwrap_number(
                player.get("pM"),
                0,
            ),
            "ball_recoveries": unwrap_number(
                player.get("bR"),
                0,
            ),
            "goals_outside_box": unwrap_number(
                player.get("gOB"),
                0,
            ),
            "player_of_match_awards": unwrap_number(
                player.get("mOM"),
                0,
            ),
            "player_of_match_points": unwrap_number(
                player.get("mOMPts"),
                0,
            ),
        },

        # ----------------------------------------------------
        # CURRENT 2026/27 MATCHDAY STATE
        # ----------------------------------------------------
        "current_matchday": {
            "matchday": clean_string(player.get("mdId")),
            "points": unwrap_number(
                player.get("curGDPts"),
                0,
            ),
            "played": bool(
                unwrap_number(player.get("isPlayed"), 0)
            ),
            "current_match": current_match,
            "next_match": next_match,
        },

        # Keep the less-understood UEFA category fields.
        # We can decipher these later without needing the
        # original feed to remain unchanged.
        "uefa_categories": {
            f"category{i}": unwrap_number(
                player.get(f"category{i}"),
                0,
            )
            for i in range(1, 16)
        },

        "uefa_extra": {
            "rating": unwrap_number(
                player.get("rating"),
                0,
            ),
            "avg_player_points": unwrap_number(
                player.get("avgPlayerPts"),
                0,
            ),
            "avg_player_value": unwrap_number(
                player.get("avgPlayerValue"),
                0,
            ),
            "last_gameday_points": unwrap_number(
                player.get("lastGdPoints"),
                0,
            ),
            "daily_total_points": unwrap_number(
                player.get("dTotPts"),
                0,
            ),
            "pot_id": clean_string(player.get("ptId")),
            "pot_name": clean_string(player.get("ptName")),
        },
    }


def normalize_players(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    player_list = (
        payload
        .get("data", {})
        .get("value", {})
        .get("playerList", [])
    )

    if not isinstance(player_list, list):
        raise ValueError(
            "Could not locate data.value.playerList "
            "in UEFA players feed"
        )

    normalized = [
        normalize_player(player)
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
# TEAM NORMALIZATION
# ============================================================

def normalize_team(
    team: dict[str, Any],
) -> dict[str, Any]:
    upcoming = team.get("upcomingMatchesList") or []

    return {
        "id": clean_string(team.get("id")),
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
        "eliminated": team.get("isEliminated"),
        "pot": {
            "id": clean_string(team.get("htPtId")),
            "name": clean_string(team.get("htPtName")),
        },
        "next_match": (
            normalize_match_reference(upcoming[0])
            if upcoming
            else None
        ),
    }


def normalize_teams(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    teams = payload.get("data", {}).get("value", [])

    if not isinstance(teams, list):
        raise ValueError(
            "Could not locate data.value in UEFA teams feed"
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
# FIXTURE NORMALIZATION
# ============================================================

def normalize_fixture_match(
    matchday_id: Any,
    match: dict[str, Any],
) -> dict[str, Any]:
    return {
        "match_id": clean_string(match.get("mId")),
        "matchday": int(matchday_id),
        "fantasy_gameday_id": clean_string(
            match.get("gdId")
        ),
        "kickoff": clean_string(match.get("dateTime")),
        "lock_time": clean_string(
            match.get("dateTimeLock")
        ),

        "home": {
            "id": clean_string(match.get("htId")),
            "name": clean_string(match.get("htName")),
            "code": clean_string(match.get("htCCode")),
            "score": clean_string(match.get("htScore")),
        },

        "away": {
            "id": clean_string(match.get("atId")),
            "name": clean_string(match.get("atName")),
            "code": clean_string(match.get("atCCode")),
            "score": clean_string(match.get("atScore")),
        },

        "status": clean_string(match.get("matchStatus")),

        "is_live": bool(
            unwrap_number(match.get("isLive"), 0)
        ),
        "feed_live": str(
            match.get("isFeedLive", "0")
        ) == "1",
        "locked": bool(
            unwrap_number(match.get("gmIsLocked"), 0)
        ),
        "postponed": bool(
            unwrap_number(
                match.get("isMatchPostponed"),
                0,
            )
        ),
        "lineup_announced": bool(
            unwrap_number(
                match.get("lineupAnnounced"),
                0,
            )
        ),

        "venue": {
            "stadium_id": clean_string(
                match.get("stadiumId")
            ),
            "stadium": clean_string(
                match.get("stadiumName")
            ),
            "city": clean_string(
                match.get("venueName")
            ),
            "country_code": clean_string(
                match.get("venueCountryCode")
            ),
        },
    }


def normalize_fixtures(
    payload: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    matchdays = payload.get("data", {}).get("value", [])

    if not isinstance(matchdays, list):
        raise ValueError(
            "Could not locate data.value "
            "in UEFA fixtures feed"
        )

    normalized_matchdays = []
    normalized_matches = []

    for matchday in matchdays:
        if not isinstance(matchday, dict):
            continue

        md_id = matchday.get("mdId")

        md_record = {
            "matchday": md_id,
            "phase_id": matchday.get("phId"),
            "deadline": clean_string(
                matchday.get("deadline")
            ),
            "is_current": bool(
                unwrap_number(
                    matchday.get("mdIsCurrent"),
                    0,
                )
            ),
            "is_locked": bool(
                unwrap_number(
                    matchday.get("mdIsLocked"),
                    0,
                )
            ),
            "fantasy_gameday_current": bool(
                unwrap_number(
                    matchday.get("gdIsCurrent"),
                    0,
                )
            ),
            "fantasy_gameday_locked": bool(
                unwrap_number(
                    matchday.get("gdIsLocked"),
                    0,
                )
            ),
            "subs_allowed": unwrap_number(
                matchday.get("subsAllowed"),
                0,
            ),
            "match_ids": [],
        }

        matches = matchday.get("match") or []

        for match in matches:
            if not isinstance(match, dict):
                continue

            normalized = normalize_fixture_match(
                md_id,
                match,
            )

            normalized_matches.append(normalized)

            md_record["match_ids"].append(
                normalized["match_id"]
            )

        normalized_matchdays.append(md_record)

    normalized_matches.sort(
        key=lambda match: (
            match["matchday"],
            match["kickoff"],
            match["match_id"],
        )
    )

    normalized_matchdays.sort(
        key=lambda md: md["matchday"]
    )

    return normalized_matchdays, normalized_matches


# ============================================================
# PRESEASON SNAPSHOT
# ============================================================

def save_preseason_snapshot(
    raw_payloads: dict[str, dict[str, Any]],
) -> bool:
    marker = PRESEASON_ARCHIVE_DIR / "_ARCHIVED.txt"

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

    for name, payload in raw_payloads.items():
        write_json(
            PRESEASON_ARCHIVE_DIR / f"{name}_raw.json",
            payload,
        )

    marker.write_text(
        (
            "Permanent preseason snapshot of UEFA UWCL "
            "Fantasy feeds.\n"
            "Captured before the first 2026/27 "
            "league-phase matches.\n"
            "Player statistical totals appear to contain "
            "carried-forward 2025/26 UWCL data.\n"
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

    raw_payloads: dict[str, dict[str, Any]] = {}

    for name, url in URLS.items():
        raw_payloads[name] = fetch_json(url)

        # Always preserve the latest untouched response too.
        write_json(
            RAW_DIR / f"{name}_raw.json",
            raw_payloads[name],
        )

    archived_now = save_preseason_snapshot(
        raw_payloads
    )

    players = normalize_players(
        raw_payloads["players"]
    )

    teams = normalize_teams(
        raw_payloads["teams"]
    )

    matchdays, matches = normalize_fixtures(
        raw_payloads["fixtures"]
    )

    current_matchday = next(
        (
            md["matchday"]
            for md in matchdays
            if md["is_current"]
        ),
        None,
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

    metadata = {
        "competition": "UWCL",
        "season": CURRENT_SEASON,
        "current_matchday": current_matchday,
        "historical_stats": {
            "season": HISTORICAL_STATS_SEASON,
            "status": (
                "preseason_carried_forward_unverified"
            ),
            "note": (
                "Before the first 2026/27 matches, UEFA's "
                "player feed contains non-zero totals that "
                "appear to be carried forward from 2025/26. "
                "The permanent preseason raw snapshot is "
                "retained for comparison after UEFA updates "
                "the feed."
            ),
        },
        "counts": {
            "players": len(players),
            "teams": len(teams),
            "matches": len(matches),
            "matchdays": len(matchdays),
        },
        "sources": deepcopy(URLS),
        "fetched_at_utc": fetched_at,
        "preseason_archive": {
            "path": str(PRESEASON_ARCHIVE_DIR),
            "created_this_run": archived_now,
        },
    }

    write_json(
        DATA_DIR / "meta.json",
        metadata,
    )

    print()
    print("UWCL fetch complete.")
    print(f"Players: {len(players)}")
    print(f"Teams: {len(teams)}")
    print(f"Matches: {len(matches)}")
    print(f"Matchdays: {len(matchdays)}")
    print(f"Current matchday: {current_matchday}")
    print(f"Fetched at: {fetched_at}")

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
