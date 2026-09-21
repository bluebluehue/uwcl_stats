#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path("data/uwcl")
PLAYERS_PATH = DATA_DIR / "players.json"
TEAMS_PATH = DATA_DIR / "teams.json"
FIXTURES_PATH = DATA_DIR / "fixtures.json"
META_PATH = DATA_DIR / "meta.json"
OUTPUT_PATH = DATA_DIR / "transformed_data.json"
TEAM_POSITION_PATH = DATA_DIR / "team_position_fixture_ratings.json"

TEAM_STRENGTHS_PATH = DATA_DIR / "team_strengths.json"
GK_ROLES_PATH = DATA_DIR / "gk_roles.json"

FIXTURE_STRENGTH_SCALE = 12.0
HOME_BONUS = 4.0
AWAY_PENALTY = -4.0
FIXTURE_MIN = 20.0
FIXTURE_MAX = 85.0

COMPARISON_PERCENTILE_WEIGHT = 0.70
COMPARISON_RAW_WEIGHT = 0.30

OUTFIELD_DECISION_WEIGHTS = {
    "fixture": 0.55,
    "form": 0.45,
}
GK_DECISION_WEIGHTS = {
    "fixture": 0.85,
    "form": 0.15,
}
ROLE_CONFIDENCE_BASELINE = 35.0


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def percentile_rank(value: float, population: list[float]) -> float:
    values = sorted(float(v) for v in population if v is not None and math.isfinite(float(v)))
    if not values:
        return 50.0
    if len(values) == 1:
        return 50.0

    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return round((below + 0.5 * equal) / len(values) * 100.0, 1)


def comparison_rating(raw_rating: float, percentile: float) -> float:
    score = (
        COMPARISON_PERCENTILE_WEIGHT * percentile
        + COMPARISON_RAW_WEIGHT * raw_rating
    )
    return round(clamp(score), 1)



def parse_kickoff(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def build_team_fixture_index(
    matches: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for match in matches:
        matchday = safe_int(match.get("matchday"))
        kickoff = str(match.get("kickoff") or "")
        kickoff_dt = parse_kickoff(kickoff)

        home = match.get("home") or {}
        away = match.get("away") or {}

        home_id = str(home.get("id") or "")
        away_id = str(away.get("id") or "")

        if home_id:
            index[home_id].append({
                "match_id": str(match.get("match_id") or ""),
                "matchday": matchday,
                "kickoff": kickoff,
                "kickoff_dt": kickoff_dt,
                "home_away": "H",
                "opponent_id": away_id,
                "opponent": str(away.get("name") or ""),
                "opponent_code": str(away.get("code") or ""),
                "lineup_announced": bool(match.get("lineup_announced")),
                "status": str(match.get("status") or ""),
            })

        if away_id:
            index[away_id].append({
                "match_id": str(match.get("match_id") or ""),
                "matchday": matchday,
                "kickoff": kickoff,
                "kickoff_dt": kickoff_dt,
                "home_away": "A",
                "opponent_id": home_id,
                "opponent": str(home.get("name") or ""),
                "opponent_code": str(home.get("code") or ""),
                "lineup_announced": bool(match.get("lineup_announced")),
                "status": str(match.get("status") or ""),
            })

    for team_id, fixtures in index.items():
        fixtures.sort(
            key=lambda f: (
                safe_int(f.get("matchday"), 999),
                f.get("kickoff_dt") or datetime.max,
            )
        )

    return index


def day_info_for_matchday(
    matches: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_md: dict[int, list[datetime]] = defaultdict(list)

    for match in matches:
        kickoff = parse_kickoff(str(match.get("kickoff") or ""))
        if kickoff is not None:
            by_md[safe_int(match.get("matchday"))].append(kickoff)

    date_order: dict[int, list[Any]] = {}
    for md, dates in by_md.items():
        date_order[md] = sorted({d.date() for d in dates})

    result: dict[str, dict[str, Any]] = {}
    for match in matches:
        match_id = str(match.get("match_id") or "")
        kickoff = parse_kickoff(str(match.get("kickoff") or ""))
        md = safe_int(match.get("matchday"))

        if not match_id or kickoff is None:
            continue

        dates = date_order.get(md, [])
        day_number = dates.index(kickoff.date()) + 1 if kickoff.date() in dates else None

        result[match_id] = {
            "day_number": day_number,
            "day_short": kickoff.strftime("%a").upper(),
            "date_iso": kickoff.date().isoformat(),
        }

    return result


def fixture_rating(
    fixture: dict[str, Any] | None,
    strength_by_team_id: dict[str, dict[str, Any]],
    opta_mean: float,
    opta_sd: float,
) -> float | None:
    if not fixture:
        return None

    opponent_id = str(fixture.get("opponent_id") or "")
    strength = strength_by_team_id.get(opponent_id)

    if not strength:
        return 50.0

    opta = safe_float(strength.get("opta_rating"), opta_mean)

    if opta_sd <= 0:
        z_score = 0.0
    else:
        z_score = (opta - opta_mean) / opta_sd

    # Higher Opta rating = stronger opponent = harder fantasy fixture.
    base = 50.0 - FIXTURE_STRENGTH_SCALE * z_score

    location = str(fixture.get("home_away") or "").upper()
    if location == "H":
        base += HOME_BONUS
    elif location == "A":
        base += AWAY_PENALTY

    return round(clamp(base, FIXTURE_MIN, FIXTURE_MAX), 1)


def fixture_detail(
    fixture: dict[str, Any] | None,
    strength_by_team_id: dict[str, dict[str, Any]],
    opta_mean: float,
    opta_sd: float,
    day_by_match_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not fixture:
        return None

    opponent_id = str(fixture.get("opponent_id") or "")
    strength = strength_by_team_id.get(opponent_id) or {}
    day = day_by_match_id.get(str(fixture.get("match_id") or ""), {})
    rating = fixture_rating(
        fixture,
        strength_by_team_id,
        opta_mean,
        opta_sd,
    )

    return {
        "match_id": str(fixture.get("match_id") or ""),
        "matchday": safe_int(fixture.get("matchday")),
        "opponent_id": opponent_id,
        "opponent": str(fixture.get("opponent") or ""),
        "opponent_code": str(fixture.get("opponent_code") or ""),
        "home_away": str(fixture.get("home_away") or ""),
        "kickoff": str(fixture.get("kickoff") or ""),
        "day_number": day.get("day_number"),
        "day_short": day.get("day_short") or "",
        "date_iso": day.get("date_iso") or "",
        "opponent_opta_rating": (
            safe_float(strength.get("opta_rating"))
            if strength else None
        ),
        "opponent_uefa_rank": strength.get("uefa_rank"),
        "opponent_uefa_coefficient": strength.get("uefa_coefficient"),
        "rating": rating,
        "method": "opponent Opta strength z-score + home/away adjustment",
    }


def historical_metrics(player: dict[str, Any]) -> dict[str, float]:
    stats = player.get("historical_stats") or {}
    minutes = max(0.0, safe_float(stats.get("minutes")))
    factor = 90.0 / minutes if minutes > 0 else 0.0

    goals = safe_float(stats.get("goals"))
    assists = safe_float(stats.get("assists"))
    recoveries = safe_float(stats.get("ball_recoveries"))
    potm = safe_float(stats.get("player_of_match_awards"))
    saves = safe_float(stats.get("saves"))
    points = safe_float(stats.get("fantasy_points"))
    price = max(0.1, safe_float(player.get("price"), 0.1))

    return {
        "minutes": minutes,
        "points": points,
        "points_per_90": points * factor,
        "points_per_million": points / price,
        "goals": goals,
        "assists": assists,
        "ga": goals + assists,
        "ga_per_90": (goals + assists) * factor,
        "recoveries": recoveries,
        "recoveries_per_90": recoveries * factor,
        "potm": potm,
        "potm_per_90": potm * factor,
        "saves": saves,
        "saves_per_90": saves * factor,
        "clean_sheets": safe_float(stats.get("clean_sheets")),
    }


def build_form_ratings(
    rows: list[dict[str, Any]],
) -> None:
    """
    Preseason EURO PRIOR, not current form.

    This intentionally excludes price/value. Price belongs to a separate
    value decision, not a performance/form signal.
    """
    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_position[str(row.get("Position") or "")].append(row)

    for position_rows in by_position.values():
        p90_pop = [
            safe_float(r.get("Historical Points Per 90"))
            for r in position_rows
        ]
        total_pop = [
            safe_float(r.get("Previous Season Points"))
            for r in position_rows
        ]

        for row in position_rows:
            p90_pct = percentile_rank(
                safe_float(row.get("Historical Points Per 90")),
                p90_pop,
            )
            total_pct = percentile_rank(
                safe_float(row.get("Previous Season Points")),
                total_pop,
            )

            raw = 0.65 * p90_pct + 0.35 * total_pct

            minutes = safe_float(row.get("Previous Season Minutes"))
            confidence = min(1.0, minutes / 720.0)

            rating = 50.0 + confidence * (raw - 50.0)

            row["Form Rating"] = round(clamp(rating), 1)
            row["Form Confidence"] = round(confidence, 3)
            row["Form Rating Method"] = (
                "2025/26 UWCL performance prior: 65% position-relative "
                "fantasy points/90 + 35% total fantasy points; "
                "shrunk toward 50 below 720 minutes. Price is excluded."
            )


def load_gk_role_overrides() -> dict[str, dict[str, Any]]:
    if not GK_ROLES_PATH.exists():
        return {}

    try:
        payload = load_json(GK_ROLES_PATH)
    except Exception:
        return {}

    players = payload.get("players") or {}
    if isinstance(players, list):
        return {
            str(item.get("player_id") or ""): item
            for item in players
            if isinstance(item, dict) and item.get("player_id")
        }

    if isinstance(players, dict):
        return {
            str(player_id): value
            for player_id, value in players.items()
            if isinstance(value, dict)
        }

    return {}


def assign_gk_roles(
    rows: list[dict[str, Any]],
) -> None:
    """
    Conservative provisional keeper hierarchy.

    Manual overrides in data/uwcl/gk_roles.json take precedence.
    Otherwise we infer only when the 2025/26 UWCL minutes gap is clear.
    We do NOT silently call every cheapest/highest-rated keeper a starter.
    """
    overrides = load_gk_role_overrides()

    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("Position") == "GK" and row.get("Active"):
            by_team[str(row.get("Team ID") or "")].append(row)

    for row in rows:
        if row.get("Position") != "GK":
            row["GK Role"] = ""
            row["GK Role Confidence"] = None
            row["GK Role Source"] = ""
            continue

        player_id = str(row.get("Player ID") or "")
        override = overrides.get(player_id)
        if override:
            row["GK Role"] = str(override.get("role") or "Uncertain")
            row["GK Role Confidence"] = override.get("confidence")
            row["GK Role Source"] = str(
                override.get("source")
                or "manual gk_roles.json override"
            )

    for team_id, keepers in by_team.items():
        # Do not overwrite manual roles.
        auto_candidates = [
            row for row in keepers
            if not row.get("GK Role")
        ]
        if not auto_candidates:
            continue

        ranked = sorted(
            auto_candidates,
            key=lambda row: safe_float(row.get("Previous Season Minutes")),
            reverse=True,
        )

        top = ranked[0]
        top_minutes = safe_float(top.get("Previous Season Minutes"))
        second_minutes = (
            safe_float(ranked[1].get("Previous Season Minutes"))
            if len(ranked) > 1 else 0.0
        )

        clear_high = (
            top_minutes >= 360
            and top_minutes >= second_minutes + 180
            and top_minutes >= max(1.5 * second_minutes, 360)
        )
        clear_medium = (
            top_minutes >= 180
            and top_minutes >= second_minutes + 120
        )

        if len(ranked) == 1:
            top["GK Role"] = "Likely starter"
            top["GK Role Confidence"] = 0.65
            top["GK Role Source"] = (
                "only active fantasy goalkeeper for club; provisional"
            )
        elif clear_high:
            top["GK Role"] = "Likely starter"
            top["GK Role Confidence"] = 0.75
            top["GK Role Source"] = (
                "clear lead in 2025/26 UWCL goalkeeper minutes; provisional"
            )
        elif clear_medium:
            top["GK Role"] = "Likely starter"
            top["GK Role Confidence"] = 0.60
            top["GK Role Source"] = (
                "lead in 2025/26 UWCL goalkeeper minutes; provisional"
            )
        else:
            top["GK Role"] = "Uncertain"
            top["GK Role Confidence"] = 0.35
            top["GK Role Source"] = (
                "2025/26 UWCL minutes do not establish a clear current starter"
            )

        for backup in ranked[1:]:
            if backup.get("GK Role"):
                continue

            # If the hierarchy was uncertain, preserve that uncertainty rather
            # than pretending the lower-minute keeper is definitely a backup.
            if top.get("GK Role") == "Uncertain":
                backup["GK Role"] = "Uncertain"
                backup["GK Role Confidence"] = 0.25
                backup["GK Role Source"] = (
                    "club goalkeeper hierarchy unclear from available UWCL data"
                )
            else:
                backup["GK Role"] = "Backup"
                backup["GK Role Confidence"] = 0.55
                backup["GK Role Source"] = (
                    "behind provisional likely starter in 2025/26 UWCL minutes"
                )


def availability_confidence(player: dict[str, Any]) -> tuple[float, str]:
    if not player.get("active"):
        return 0.0, "Inactive in UEFA fantasy feed"

    status = player.get("status") or {}
    code = str(status.get("code") or "").upper()
    text = str(status.get("availability_text") or "").strip().lower()

    if code == "I":
        return 0.35, "UEFA status: injured"
    if code == "D":
        return 0.70, "UEFA status: doubtful"
    if code == "S":
        return 0.20, "UEFA status: suspended"

    if "unlikely to start" in text:
        return 0.60, "UEFA availability text: unlikely to start"
    if "in contention" in text:
        return 1.00, "UEFA availability text: in contention"

    return 1.00, "No negative UEFA availability signal"


def apply_comparison_and_decision(
    rows: list[dict[str, Any]],
) -> None:
    active_rows = [r for r in rows if r.get("Active")]

    fixture_pop = [
        safe_float(r.get("Next Fixture Rating"), 50.0)
        for r in active_rows
        if r.get("Next Fixture Rating") is not None
    ]
    following_pop = [
        safe_float(r.get("Following Fixture Rating"), 50.0)
        for r in active_rows
        if r.get("Following Fixture Rating") is not None
    ]

    by_position: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in active_rows:
        by_position[str(row.get("Position") or "")].append(row)

    for row in rows:
        pos = str(row.get("Position") or "")

        raw_fix = safe_float(row.get("Next Fixture Rating"), 50.0)
        fix_pct = percentile_rank(raw_fix, fixture_pop)
        row["Comparison Fixture Rating"] = comparison_rating(
            raw_fix,
            fix_pct,
        )

        if row.get("Following Fixture Rating") is None:
            row["Comparison Following Fixture Rating"] = None
        else:
            raw_follow = safe_float(
                row.get("Following Fixture Rating"),
                50.0,
            )
            follow_pct = percentile_rank(
                raw_follow,
                following_pop,
            )
            row["Comparison Following Fixture Rating"] = comparison_rating(
                raw_follow,
                follow_pct,
            )

        peers = by_position.get(pos) or active_rows
        form_pop = [
            safe_float(r.get("Form Rating"), 50.0)
            for r in peers
        ]
        form_raw = safe_float(row.get("Form Rating"), 50.0)
        form_pct = percentile_rank(form_raw, form_pop)
        row["Comparison Form Rating"] = comparison_rating(
            form_raw,
            form_pct,
        )

        if pos == "GK":
            base = (
                row["Comparison Fixture Rating"]
                * GK_DECISION_WEIGHTS["fixture"]
                + row["Comparison Form Rating"]
                * GK_DECISION_WEIGHTS["form"]
            )
        else:
            base = (
                row["Comparison Fixture Rating"]
                * OUTFIELD_DECISION_WEIGHTS["fixture"]
                + row["Comparison Form Rating"]
                * OUTFIELD_DECISION_WEIGHTS["form"]
            )

        row["Base Decision Rating Before Availability"] = round(
            base,
            1,
        )

        confidence = safe_float(
            row.get("Availability Confidence"),
            1.0,
        )
        adjusted = (
            ROLE_CONFIDENCE_BASELINE
            + confidence * (base - ROLE_CONFIDENCE_BASELINE)
        )
        row["Decision Rating"] = round(clamp(adjusted), 1)


def build_team_position_fixture_ratings(
    rows: list[dict[str, Any]],
    current_matchday: int,
) -> dict[str, Any]:
    """
    Create a team x fantasy-position fixture board.

    Fixture strength is team-level, but the score is translated by fantasy
    position so attacking roles care about opponent defensive strength and
    GK/DEF care about opponent attacking strength. With no market team-totals
    wired in yet, Opta is used as the opponent-strength backbone.

    Position adjustments are intentionally modest:
      - GK/DEF receive a clean-sheet-oriented boost/penalty based on opponent strength.
      - MID/FWD receive an attacking-oriented boost/penalty based on opponent strength.
    """
    by_team: dict[str, dict[str, Any]] = {}

    # One representative row per team is enough for fixture metadata.
    representative: dict[str, dict[str, Any]] = {}
    for row in rows:
        team_id = str(row.get("Team ID") or "")
        if team_id and team_id not in representative:
            representative[team_id] = row

    position_bias = {
        "GK": 1.05,
        "DEF": 1.00,
        "MID": 0.92,
        "FWD": 0.98,
    }

    for team_id, row in representative.items():
        fixture = row.get("Next Fixture Details") or {}
        follow = row.get("Following Fixture Details") or {}

        base_current = safe_float(row.get("Comparison Fixture Rating"), 50.0)
        base_follow = (
            safe_float(row.get("Comparison Following Fixture Rating"), 50.0)
            if row.get("Comparison Following Fixture Rating") is not None
            else None
        )

        opp_opta = safe_float(fixture.get("opponent_opta_rating"), 0.0)

        # Opponent-strength direction:
        # weaker opponent -> better for both attacking and defensive fantasy outlook.
        # We vary amplitude by position rather than invent separate attack/defense models.
        team_positions: dict[str, Any] = {}
        for pos in ("GK","DEF","MID","FWD"):
            bias = position_bias[pos]

            # Center on the team fixture comparison score, with a small role-specific
            # spread to make the board useful without overstating precision.
            if pos in ("GK","DEF"):
                current = clamp(50.0 + (base_current - 50.0) * bias + (2.0 if base_current >= 50 else -2.0))
                following = (
                    clamp(50.0 + (base_follow - 50.0) * bias + (2.0 if base_follow >= 50 else -2.0))
                    if base_follow is not None else None
                )
                lens = "clean-sheet / defensive fixture lens"
            else:
                current = clamp(50.0 + (base_current - 50.0) * bias)
                following = (
                    clamp(50.0 + (base_follow - 50.0) * bias)
                    if base_follow is not None else None
                )
                lens = "attacking-return fixture lens"

            team_positions[pos] = {
                "current": round(current, 1),
                "following": round(following, 1) if following is not None else None,
                "lens": lens,
            }

        by_team[team_id] = {
            "team_id": team_id,
            "club": row.get("Club"),
            "club_name": row.get("Club Name"),
            "current_matchday": current_matchday,
            "fixture": fixture,
            "following_fixture": follow,
            "positions": team_positions,
        }

    return {
        "competition": "UWCL",
        "season": "2026/27",
        "current_matchday": current_matchday,
        "model": {
            "status": "provisional_preseason_v1",
            "note": (
                "Team-position fixture ratings use the Opta-driven team fixture score "
                "with modest position lenses. They are not xG/market-derived attack and "
                "clean-sheet probabilities yet."
            ),
        },
        "teams": sorted(
            by_team.values(),
            key=lambda x: str(x.get("club_name") or "")
        ),
    }


def transform() -> dict[str, Any]:
    players_payload = load_json(PLAYERS_PATH)
    teams_payload = load_json(TEAMS_PATH)
    fixtures_payload = load_json(FIXTURES_PATH)
    meta = load_json(META_PATH)
    strengths_payload = load_json(TEAM_STRENGTHS_PATH)

    players = players_payload.get("players") or []
    teams = teams_payload.get("teams") or []
    matches = fixtures_payload.get("matches") or []

    strength_by_team_id = {
        str(team.get("team_id") or ""): team
        for team in (strengths_payload.get("teams") or [])
    }

    opta_values = [
        safe_float(team.get("opta_rating"))
        for team in strength_by_team_id.values()
        if team.get("opta_rating") is not None
    ]
    opta_mean = (
        sum(opta_values) / len(opta_values)
        if opta_values else 50.0
    )
    if len(opta_values) > 1:
        opta_sd = math.sqrt(
            sum((value - opta_mean) ** 2 for value in opta_values)
            / len(opta_values)
        )
    else:
        opta_sd = 1.0

    team_fixtures = build_team_fixture_index(matches)
    day_by_match_id = day_info_for_matchday(matches)
    current_matchday = safe_int(meta.get("current_matchday"), 1)

    rows: list[dict[str, Any]] = []

    for player in players:
        team = player.get("team") or {}
        team_id = str(team.get("id") or "")
        position = str(player.get("position") or "")
        metrics = historical_metrics(player)

        upcoming = [
            f
            for f in team_fixtures.get(team_id, [])
            if safe_int(f.get("matchday")) >= current_matchday
        ]

        current_fixture = next(
            (f for f in upcoming if safe_int(f.get("matchday")) == current_matchday),
            upcoming[0] if upcoming else None,
        )

        later = [
            f for f in upcoming
            if current_fixture is None
            or safe_int(f.get("matchday")) > safe_int(current_fixture.get("matchday"))
        ]
        following_fixture = later[0] if later else None

        current_detail = fixture_detail(
            current_fixture,
            strength_by_team_id,
            opta_mean,
            opta_sd,
            day_by_match_id,
        )
        following_detail = fixture_detail(
            following_fixture,
            strength_by_team_id,
            opta_mean,
            opta_sd,
            day_by_match_id,
        )

        next_three = []
        seen_mds = set()
        for fixture in upcoming:
            md = safe_int(fixture.get("matchday"))
            if md in seen_mds:
                continue
            seen_mds.add(md)
            detail = fixture_detail(
                fixture,
                strength_by_team_id,
                opta_mean,
                opta_sd,
                day_by_match_id,
            )
            if detail:
                next_three.append(detail)
            if len(next_three) >= 3:
                break

        next_three_ratings = [
            safe_float(f.get("rating"))
            for f in next_three
            if f.get("rating") is not None
        ]

        status = player.get("status") or {}
        availability_conf, availability_note = availability_confidence(player)

        transfer = player.get("transfer_activity") or {}
        transfer_trend = (
            safe_float(transfer.get("selected_in_pct"))
            - safe_float(transfer.get("selected_out_pct"))
        )

        row = {
            "Name": str(player.get("name") or ""),
            "Short Name": str(player.get("display_name") or player.get("name") or ""),
            "Player ID": str(player.get("id") or ""),
            "Club": str(team.get("code") or team.get("name") or ""),
            "Club Name": str(team.get("name") or ""),
            "Team ID": team_id,
            "Nationality": str((player.get("nationality") or {}).get("code") or ""),
            "Position": position,
            "Value": safe_float(player.get("price")),
            "Selected Percentage": safe_float(player.get("selected_pct")),
            "Transfer Trend Percentage": round(transfer_trend, 1),
            "Active": bool(player.get("active")),
            "Status Code": str(status.get("code") or ""),
            "Status Label": str(status.get("label") or ""),
            "Availability Text": str(status.get("availability_text") or ""),
            "Availability Confidence": round(availability_conf, 2),
            "Availability Confidence Note": availability_note,

            "Next Fixture Day": current_detail.get("day_short") if current_detail else "",
            "Next Fixture Day Number": current_detail.get("day_number") if current_detail else None,
            "Next Fixture Date ISO": current_detail.get("date_iso") if current_detail else "",
            "Next Fixture Kickoff": current_detail.get("kickoff") if current_detail else "",
            "Next Fixture Opponent": current_detail.get("opponent_code") if current_detail else "",
            "Next Fixture Opponent Name": current_detail.get("opponent") if current_detail else "",
            "Next Fixture H/A": current_detail.get("home_away") if current_detail else "",
            "Next Fixture Opponent Pot": current_detail.get("opponent_pot") if current_detail else "",
            "Next Fixture Rating": current_detail.get("rating") if current_detail else None,
            "Next Fixture Details": current_detail,

            "Following Fixture Rating": following_detail.get("rating") if following_detail else None,
            "Following Fixture Opponent": following_detail.get("opponent_code") if following_detail else "",
            "Following Fixture H/A": following_detail.get("home_away") if following_detail else "",
            "Following Fixture Details": following_detail,

            "Next Three Fixture Rating": (
                round(sum(next_three_ratings) / len(next_three_ratings), 1)
                if next_three_ratings else None
            ),
            "Next Three Fixtures": next_three,

            "Previous Season Minutes": round(metrics["minutes"], 0),
            "Previous Season Points": round(metrics["points"], 0),
            "Historical Points Per 90": round(metrics["points_per_90"], 2),
            "Previous Season Points Per Million": round(metrics["points_per_million"], 2),
            "Total Goals": round(metrics["goals"], 0),
            "Total Assists": round(metrics["assists"], 0),
            "Total Goals + Assists": round(metrics["ga"], 0),
            "Historical G+A Per 90": round(metrics["ga_per_90"], 3),
            "Total Ball Recoveries": round(metrics["recoveries"], 0),
            "Historical Recoveries Per 90": round(metrics["recoveries_per_90"], 2),
            "Total POTM": round(metrics["potm"], 0),
            "Historical POTM Per 90": round(metrics["potm_per_90"], 3),
            "Total Saves": round(metrics["saves"], 0),
            "Historical Saves Per 90": round(metrics["saves_per_90"], 2),
            "Total Clean Sheets": round(metrics["clean_sheets"], 0),

            "Current Matchday Points": safe_float((player.get("current_matchday") or {}).get("points")),
            "Current Matchday Played": bool((player.get("current_matchday") or {}).get("played")),
        }
        rows.append(row)

    build_form_ratings(rows)
    assign_gk_roles(rows)
    apply_comparison_and_decision(rows)

    rows.sort(
        key=lambda r: (
            not bool(r.get("Active")),
            -safe_float(r.get("Decision Rating")),
            str(r.get("Name") or ""),
        )
    )

    return {
        "competition": "UWCL",
        "season": "2026/27",
        "generated_from": {
            "players": str(PLAYERS_PATH),
            "teams": str(TEAMS_PATH),
            "fixtures": str(FIXTURES_PATH),
            "meta": str(META_PATH),
            "team_strengths": str(TEAM_STRENGTHS_PATH),
            "gk_role_overrides": str(GK_ROLES_PATH),
        },
        "current_matchday": current_matchday,
        "count": len(rows),
        "model": {
            "status": "provisional_preseason_v1",
            "fixture": {
                "method": "opponent Opta strength z-score + home/away adjustment",
                "primary_strength_metric": "Opta rating",
                "opta_mean": round(opta_mean, 4),
                "opta_population_sd": round(opta_sd, 4),
                "strength_scale": FIXTURE_STRENGTH_SCALE,
                "home_bonus": HOME_BONUS,
                "away_penalty": AWAY_PENALTY,
                "raw_clamp": [FIXTURE_MIN, FIXTURE_MAX],
                "note": (
                    "Opta is primary because it better reflects current cross-league team strength. "
                    "UEFA rank/coefficient are retained in team_strengths.json for context, but do not "
                    "currently drive Fixture Rating."
                ),
            },
            "form": {
                "label": "EURO PRIOR",
                "method": (
                    "2025/26 position-relative UWCL fantasy prior using "
                    "65% points/90 + 35% total points; shrunk toward neutral "
                    "for low minutes. Price/value is deliberately excluded."
                ),
                "note": (
                    "This is a historical European performance prior, not current form. "
                    "A true Form signal will use recent domestic + UWCL matches."
                ),
            },
            "decision": {
                "outfield_weights": OUTFIELD_DECISION_WEIGHTS,
                "gk_weights": GK_DECISION_WEIGHTS,
                "comparison_calibration": {
                    "percentile_weight": COMPARISON_PERCENTILE_WEIGHT,
                    "raw_weight": COMPARISON_RAW_WEIGHT,
                },
                "availability_baseline": ROLE_CONFIDENCE_BASELINE,
                "note": (
                    "Preseason Decision uses Fixture + EURO PRIOR only. "
                    "A true event-based Involvement signal is intentionally omitted until "
                    "underlying chance-creation / near-return data are available."
                ),
            },
        },
        "players": rows,
    }


def main() -> int:
    payload = transform()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    team_position_payload = build_team_position_fixture_ratings(
        payload["players"],
        payload["current_matchday"],
    )
    TEAM_POSITION_PATH.write_text(
        json.dumps(team_position_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    active = [p for p in payload["players"] if p.get("Active")]
    print(f"UWCL transformed data written: {OUTPUT_PATH}")
    print(f"Team-position fixture board written: {TEAM_POSITION_PATH}")
    print(f"Players: {len(payload['players'])}")
    print(f"Active players: {len(active)}")
    print(f"Current matchday: {payload['current_matchday']}")
    print("Model status:", payload["model"]["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
