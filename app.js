const DATA_PATHS = {
  players: "data/uwcl/players.json",
  fixtures: "data/uwcl/fixtures.json",
  meta: "data/uwcl/meta.json",
};

const state = {
  players: [],
  filtered: [],
  meta: null,
  sortKey: "selected_pct",
  sortDirection: "desc",
};

const els = {
  tbody: document.querySelector("#player-tbody"),
  empty: document.querySelector("#empty-state"),
  resultCount: document.querySelector("#result-count"),

  search: document.querySelector("#filter-search"),
  team: document.querySelector("#filter-team"),
  nationality: document.querySelector("#filter-nationality"),
  position: document.querySelector("#filter-position"),
  status: document.querySelector("#filter-status"),
  active: document.querySelector("#filter-active"),
  maxPrice: document.querySelector("#filter-max-price"),
  minOwned: document.querySelector("#filter-min-owned"),
  reset: document.querySelector("#reset-filters"),

  statusMatchday: document.querySelector("#status-matchday"),
  statusPlayers: document.querySelector("#status-players"),
  statusNationality: document.querySelector("#status-nationality"),
  statusRefresh: document.querySelector("#status-refresh"),
  statusFeeds: document.querySelector("#status-feeds"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  try {
    const [playersPayload, fixturesPayload, metaPayload] = await Promise.all([
      fetchJson(DATA_PATHS.players),
      fetchJson(DATA_PATHS.fixtures),
      fetchJson(DATA_PATHS.meta),
    ]);

    state.players = Array.isArray(playersPayload.players)
      ? playersPayload.players
      : [];

    state.meta = metaPayload;

    populateFilters(state.players);
    bindControls();
    renderStatus(metaPayload, playersPayload, fixturesPayload);
    applyFiltersAndSort();
  } catch (error) {
    console.error(error);
    showFatalError(error);
  }
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }

  return response.json();
}

function populateFilters(players) {
  const teams = uniqueSorted(
    players.map((player) => player?.team?.name).filter(Boolean)
  );

  const nationalities = uniqueSorted(
    players
      .map((player) => player?.nationality?.code)
      .filter(Boolean)
  );

  appendOptions(els.team, teams);
  appendOptions(els.nationality, nationalities);
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((a, b) =>
    String(a).localeCompare(String(b), undefined, { sensitivity: "base" })
  );
}

function appendOptions(select, values) {
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function bindControls() {
  const reactive = [
    els.search,
    els.team,
    els.nationality,
    els.position,
    els.status,
    els.active,
    els.maxPrice,
    els.minOwned,
  ];

  for (const control of reactive) {
    control.addEventListener(
      control.matches('input[type="search"], input[type="number"]')
        ? "input"
        : "change",
      applyFiltersAndSort
    );
  }

  els.reset.addEventListener("click", () => {
    els.search.value = "";
    els.team.value = "";
    els.nationality.value = "";
    els.position.value = "";
    els.status.value = "";
    els.active.checked = true;
    els.maxPrice.value = "";
    els.minOwned.value = "";

    state.sortKey = "selected_pct";
    state.sortDirection = "desc";

    updateSortIndicators();
    applyFiltersAndSort();
  });

  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;

      if (state.sortKey === key) {
        state.sortDirection =
          state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDirection = defaultDirectionFor(key);
      }

      updateSortIndicators();
      applyFiltersAndSort();
    });
  }

  updateSortIndicators();
}

function defaultDirectionFor(key) {
  return [
    "price",
    "selected_pct",
    "minutes",
    "points",
    "goals",
    "assists",
    "recoveries",
    "potm",
  ].includes(key)
    ? "desc"
    : "asc";
}

function applyFiltersAndSort() {
  const query = els.search.value.trim().toLowerCase();
  const team = els.team.value;
  const nationality = els.nationality.value;
  const position = els.position.value;
  const status = els.status.value;
  const activeOnly = els.active.checked;

  const maxPrice =
    els.maxPrice.value === "" ? null : Number(els.maxPrice.value);

  const minOwned =
    els.minOwned.value === "" ? null : Number(els.minOwned.value);

  state.filtered = state.players.filter((player) => {
    if (activeOnly && !player.active) return false;
    if (team && player?.team?.name !== team) return false;
    if (
      nationality &&
      player?.nationality?.code !== nationality
    ) {
      return false;
    }
    if (position && player.position !== position) return false;

    if (status === "available" && hasFlag(player)) return false;
    if (status === "flagged" && !hasFlag(player)) return false;

    const price = numberOrNull(player.price);
    const owned = numberOrNull(player.selected_pct);

    if (
      maxPrice !== null &&
      price !== null &&
      price > maxPrice
    ) {
      return false;
    }

    if (
      minOwned !== null &&
      owned !== null &&
      owned < minOwned
    ) {
      return false;
    }

    if (query) {
      const haystack = [
        player.name,
        player.display_name,
        player.latin_name,
        player?.team?.name,
        player?.team?.code,
        player?.nationality?.code,
        player.position,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      if (!haystack.includes(query)) return false;
    }

    return true;
  });

  state.filtered.sort(comparePlayers);
  renderPlayers(state.filtered);
}

function comparePlayers(a, b) {
  const aValue = sortValue(a, state.sortKey);
  const bValue = sortValue(b, state.sortKey);

  let comparison = 0;

  if (
    typeof aValue === "number" &&
    typeof bValue === "number"
  ) {
    comparison = aValue - bValue;
  } else {
    comparison = String(aValue ?? "").localeCompare(
      String(bValue ?? ""),
      undefined,
      { numeric: true, sensitivity: "base" }
    );
  }

  return state.sortDirection === "asc"
    ? comparison
    : comparison * -1;
}

function sortValue(player, key) {
  const stats = player.historical_stats || {};

  switch (key) {
    case "name":
      return player.name || "";
    case "team":
      return player?.team?.name || "";
    case "nationality":
      return player?.nationality?.code || "";
    case "position":
      return positionOrder(player.position);
    case "price":
      return numberOrZero(player.price);
    case "selected_pct":
      return numberOrZero(player.selected_pct);
    case "status":
      return hasFlag(player) ? 1 : 0;
    case "fixture":
      return fixtureLabel(player);
    case "minutes":
      return numberOrZero(stats.minutes);
    case "points":
      return numberOrZero(stats.fantasy_points);
    case "goals":
      return numberOrZero(stats.goals);
    case "assists":
      return numberOrZero(stats.assists);
    case "recoveries":
      return numberOrZero(stats.ball_recoveries);
    case "potm":
      return numberOrZero(stats.player_of_match_awards);
    default:
      return "";
  }
}

function positionOrder(position) {
  return {
    GK: 1,
    DEF: 2,
    MID: 3,
    FWD: 4,
  }[position] ?? 99;
}

function renderPlayers(players) {
  els.tbody.innerHTML = "";
  els.resultCount.textContent = players.length.toLocaleString();

  els.empty.hidden = players.length !== 0;
  document.querySelector(".table-wrap").hidden =
    players.length === 0;

  const fragment = document.createDocumentFragment();

  for (const player of players) {
    fragment.append(buildPlayerRow(player));
  }

  els.tbody.append(fragment);
}

function buildPlayerRow(player) {
  const tr = document.createElement("tr");
  const stats = player.historical_stats || {};
  const fixture = getFixture(player);

  appendCell(tr, player.name || "—", "player-name");
  appendCell(tr, player?.team?.name || "—", "team-name");

  const nat = document.createElement("td");
  nat.innerHTML = player?.nationality?.code
    ? `<span class="nat-pill">${escapeHtml(player.nationality.code)}</span>`
    : "—";
  tr.append(nat);

  const pos = document.createElement("td");
  pos.innerHTML = `<span class="position-pill">${escapeHtml(
    player.position || "—"
  )}</span>`;
  tr.append(pos);

  appendCell(
    tr,
    formatPrice(player.price),
    "num"
  );

  appendCell(
    tr,
    formatPercent(player.selected_pct),
    "num"
  );

  tr.append(buildStatusCell(player));
  tr.append(buildFixtureCell(fixture));

  appendCell(
    tr,
    formatNumber(stats.minutes),
    "num historic"
  );
  appendCell(
    tr,
    formatNumber(stats.fantasy_points),
    "num historic"
  );
  appendCell(
    tr,
    formatNumber(stats.goals),
    "num historic"
  );
  appendCell(
    tr,
    formatNumber(stats.assists),
    "num historic"
  );
  appendCell(
    tr,
    formatNumber(stats.ball_recoveries),
    "num historic"
  );
  appendCell(
    tr,
    formatNumber(stats.player_of_match_awards),
    "num historic"
  );

  return tr;
}

function appendCell(tr, value, className = "") {
  const td = document.createElement("td");
  td.textContent = value;
  if (className) td.className = className;
  tr.append(td);
}

function buildStatusCell(player) {
  const td = document.createElement("td");
  const flagged = hasFlag(player);

  const label =
    player?.status?.label ||
    player?.status?.code ||
    (flagged ? "Flagged" : "Available");

  const pill = document.createElement("span");
  pill.className = `status-pill ${flagged ? "flagged" : "available"}`;
  pill.textContent = label;
  td.append(pill);

  const detail = player?.status?.availability_text;
  if (detail) {
    const small = document.createElement("span");
    small.className = "status-detail";
    small.textContent = detail;
    small.title = detail;
    td.append(small);
  }

  return td;
}

function hasFlag(player) {
  return Boolean(
    player?.status?.code ||
    player?.status?.availability_text
  );
}

function getFixture(player) {
  return (
    player?.current_matchday?.current_match ||
    player?.current_matchday?.next_match ||
    null
  );
}

function buildFixtureCell(fixture) {
  const td = document.createElement("td");

  if (!fixture) {
    td.textContent = "—";
    return td;
  }

  const opponent =
    fixture.opponent ||
    fixture.opponent_code ||
    "TBC";

  const location =
    String(fixture.home_away || "").toUpperCase();

  const locLabel =
    location === "H"
      ? "Home"
      : location === "A"
      ? "Away"
      : location || "";

  const main = document.createElement("span");
  main.className = "fixture-main";
  main.textContent = locLabel
    ? `${opponent} · ${locLabel}`
    : opponent;

  td.append(main);

  if (fixture.kickoff) {
    const sub = document.createElement("span");
    sub.className = "fixture-sub";
    sub.textContent = formatKickoff(fixture.kickoff);
    td.append(sub);
  }

  return td;
}

function fixtureLabel(player) {
  const fixture = getFixture(player);
  if (!fixture) return "";

  return [
    fixture.opponent,
    fixture.opponent_code,
    fixture.home_away,
    fixture.kickoff,
  ]
    .filter(Boolean)
    .join(" ");
}

function renderStatus(meta, playersPayload) {
  const counts = meta?.counts || {};
  const nationality = meta?.nationality_data || {};
  const feedStatus = meta?.feed_status || {};

  els.statusMatchday.textContent =
    meta?.current_matchday ?? "—";

  els.statusPlayers.textContent =
    counts.players ??
    playersPayload.count ??
    state.players.length;

  const activeMatched =
    nationality.active_matched_players;
  const activePlayers =
    nationality.active_players;

  if (
    activeMatched !== undefined &&
    activePlayers !== undefined
  ) {
    els.statusNationality.textContent =
      `${activeMatched}/${activePlayers} active`;
  } else {
    els.statusNationality.textContent =
      `${nationality.matched_players ?? "—"} matched`;
  }

  els.statusRefresh.textContent =
    formatTimestamp(meta?.fetched_at_utc);

  els.statusFeeds.innerHTML = "";

  for (const name of ["players", "teams", "fixtures"]) {
    const value = feedStatus[name] || "unknown";
    const span = document.createElement("span");
    span.className =
      `feed-pill ${value === "live" ? "live" : "cached"}`;
    span.textContent =
      `${capitalize(name)}: ${prettyFeedStatus(value)}`;
    els.statusFeeds.append(span);
  }
}

function prettyFeedStatus(value) {
  if (value === "live") return "live";
  if (value === "cached_last_known_good") {
    return "cached";
  }
  return value || "unknown";
}

function formatTimestamp(value) {
  if (!value) return "Unknown";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatKickoff(value) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatPrice(value) {
  const number = numberOrNull(value);
  return number === null
    ? "—"
    : `€${number.toFixed(1)}m`;
}

function formatPercent(value) {
  const number = numberOrNull(value);
  return number === null
    ? "—"
    : `${number.toFixed(
        Number.isInteger(number) ? 0 : 1
      )}%`;
}

function formatNumber(value) {
  const number = numberOrNull(value);
  return number === null
    ? "—"
    : number.toLocaleString();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function numberOrZero(value) {
  return numberOrNull(value) ?? 0;
}

function updateSortIndicators() {
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.classList.remove("sort-asc", "sort-desc");

    if (th.dataset.sort === state.sortKey) {
      th.classList.add(
        state.sortDirection === "asc"
          ? "sort-asc"
          : "sort-desc"
      );
    }
  }
}

function showFatalError(error) {
  const main = document.querySelector("main");
  const box = document.createElement("div");
  box.className = "error-box";
  box.innerHTML = `
    <strong>Could not load UWCL data.</strong><br>
    ${escapeHtml(error?.message || String(error))}
  `;
  main.prepend(box);
}

function capitalize(value) {
  return value
    ? value.charAt(0).toUpperCase() + value.slice(1)
    : "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
