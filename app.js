const DATA_PATHS = {
  players: "data/uwcl/players.json",
  fixtures: "data/uwcl/fixtures.json",
  meta: "data/uwcl/meta.json",
};

const STORAGE_KEYS = {
  team: "uwcl-player-explorer-my-team",
  watchlist: "uwcl-player-explorer-watchlist",
};

const state = {
  players: [],
  filtered: [],
  meta: null,
  sortKey: "selected_pct",
  sortDirection: "desc",
  page: 1,
  pageSize: 50,
  myTeam: new Set(),
  watchlist: new Set(),
};

const els = {
  tbody: document.querySelector("#player-tbody"),
  empty: document.querySelector("#empty-state"),
  resultCount: document.querySelector("#result-count"),
  teamCount: document.querySelector("#team-count"),
  watchCount: document.querySelector("#watch-count"),

  search: document.querySelector("#filter-search"),
  team: document.querySelector("#filter-team"),
  nationality: document.querySelector("#filter-nationality"),
  position: document.querySelector("#filter-position"),
  status: document.querySelector("#filter-status"),
  saved: document.querySelector("#filter-saved"),
  active: document.querySelector("#filter-active"),
  maxPrice: document.querySelector("#filter-max-price"),
  minOwned: document.querySelector("#filter-min-owned"),
  reset: document.querySelector("#reset-filters"),

  pageSize: document.querySelector("#page-size"),
  pageInfo: document.querySelector("#page-info"),
  pageInfoBottom: document.querySelector("#page-info-bottom"),

  exportAll: document.querySelector("#export-all"),
  exportView: document.querySelector("#export-view"),

  statusMatchday: document.querySelector("#status-matchday"),
  statusPlayers: document.querySelector("#status-players"),
  statusNationality: document.querySelector("#status-nationality"),
  statusRefresh: document.querySelector("#status-refresh"),
  statusFeeds: document.querySelector("#status-feeds"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  loadSavedLists();

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
    updateSavedCounts();
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

function loadSavedLists() {
  state.myTeam = new Set(readStoredArray(STORAGE_KEYS.team));
  state.watchlist = new Set(readStoredArray(STORAGE_KEYS.watchlist));
}

function readStoredArray(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.map(String) : [];
  } catch {
    return [];
  }
}

function saveLists() {
  localStorage.setItem(
    STORAGE_KEYS.team,
    JSON.stringify([...state.myTeam])
  );
  localStorage.setItem(
    STORAGE_KEYS.watchlist,
    JSON.stringify([...state.watchlist])
  );
}

function populateFilters(players) {
  appendOptions(
    els.team,
    uniqueSorted(
      players.map((player) => player?.team?.name).filter(Boolean)
    )
  );

  appendOptions(
    els.nationality,
    uniqueSorted(
      players
        .map((player) => player?.nationality?.code)
        .filter(Boolean)
    )
  );
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
    els.saved,
    els.active,
    els.maxPrice,
    els.minOwned,
  ];

  for (const control of reactive) {
    control.addEventListener(
      control.matches('input[type="search"], input[type="number"]')
        ? "input"
        : "change",
      () => {
        state.page = 1;
        applyFiltersAndSort();
      }
    );
  }

  els.pageSize.addEventListener("change", () => {
    state.pageSize = Number(els.pageSize.value) || 50;
    state.page = 1;
    renderPlayers();
  });

  els.reset.addEventListener("click", () => {
    els.search.value = "";
    els.team.value = "";
    els.nationality.value = "";
    els.position.value = "";
    els.status.value = "";
    els.saved.value = "";
    els.active.checked = true;
    els.maxPrice.value = "";
    els.minOwned.value = "";

    state.sortKey = "selected_pct";
    state.sortDirection = "desc";
    state.page = 1;

    updateSortIndicators();
    applyFiltersAndSort();
  });

  els.exportAll.addEventListener("click", () => {
    exportCsv(state.players, "uwcl_players_all.csv");
  });

  els.exportView.addEventListener("click", () => {
    exportCsv(state.filtered, "uwcl_players_current_view.csv");
  });

  for (const button of document.querySelectorAll("[data-page-action]")) {
    button.addEventListener("click", () => {
      const action = button.dataset.pageAction;
      const totalPages = getTotalPages();

      if (action === "prev" && state.page > 1) {
        state.page -= 1;
      }

      if (action === "next" && state.page < totalPages) {
        state.page += 1;
      }

      renderPlayers();
      scrollTableIntoView();
    });
  }

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

      state.page = 1;
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
  const saved = els.saved.value;
  const activeOnly = els.active.checked;

  const maxPrice =
    els.maxPrice.value === "" ? null : Number(els.maxPrice.value);

  const minOwned =
    els.minOwned.value === "" ? null : Number(els.minOwned.value);

  state.filtered = state.players.filter((player) => {
    const playerId = String(player.id);

    if (activeOnly && !player.active) return false;
    if (team && player?.team?.name !== team) return false;
    if (nationality && player?.nationality?.code !== nationality) return false;
    if (position && player.position !== position) return false;

    if (status === "available" && isFlagged(player)) return false;
    if (status === "flagged" && !isFlagged(player)) return false;

    if (saved === "team" && !state.myTeam.has(playerId)) return false;
    if (saved === "watchlist" && !state.watchlist.has(playerId)) return false;
    if (
      saved === "either" &&
      !state.myTeam.has(playerId) &&
      !state.watchlist.has(playerId)
    ) {
      return false;
    }

    const price = numberOrNull(player.price);
    const owned = numberOrNull(player.selected_pct);

    if (maxPrice !== null && price !== null && price > maxPrice) {
      return false;
    }

    if (minOwned !== null && owned !== null && owned < minOwned) {
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

  const totalPages = getTotalPages();
  if (state.page > totalPages) {
    state.page = Math.max(1, totalPages);
  }

  renderPlayers();
}

function comparePlayers(a, b) {
  const aValue = sortValue(a, state.sortKey);
  const bValue = sortValue(b, state.sortKey);

  let comparison = 0;

  if (typeof aValue === "number" && typeof bValue === "number") {
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
    case "name": return player.name || "";
    case "team": return player?.team?.name || "";
    case "nationality": return player?.nationality?.code || "";
    case "position": return positionOrder(player.position);
    case "price": return numberOrZero(player.price);
    case "selected_pct": return numberOrZero(player.selected_pct);
    case "status": return isFlagged(player) ? 1 : 0;
    case "fixture": return fixtureLabel(player);
    case "minutes": return numberOrZero(stats.minutes);
    case "points": return numberOrZero(stats.fantasy_points);
    case "goals": return numberOrZero(stats.goals);
    case "assists": return numberOrZero(stats.assists);
    case "recoveries": return numberOrZero(stats.ball_recoveries);
    case "potm": return numberOrZero(stats.player_of_match_awards);
    default: return "";
  }
}

function positionOrder(position) {
  return { GK: 1, DEF: 2, MID: 3, FWD: 4 }[position] ?? 99;
}

function getTotalPages() {
  return Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
}

function getCurrentPagePlayers() {
  const start = (state.page - 1) * state.pageSize;
  return state.filtered.slice(start, start + state.pageSize);
}

function renderPlayers() {
  const players = getCurrentPagePlayers();

  els.tbody.innerHTML = "";
  els.resultCount.textContent = state.filtered.length.toLocaleString();

  els.empty.hidden = state.filtered.length !== 0;
  document.querySelector(".table-wrap").hidden =
    state.filtered.length === 0;

  const fragment = document.createDocumentFragment();

  for (const player of players) {
    fragment.append(buildPlayerRow(player));
  }

  els.tbody.append(fragment);
  updatePager();
  updateSavedCounts();
}

function updatePager() {
  const totalPages = getTotalPages();
  const text = `Page ${state.page} of ${totalPages}`;

  els.pageInfo.textContent = text;
  els.pageInfoBottom.textContent = text;

  for (const button of document.querySelectorAll('[data-page-action="prev"]')) {
    button.disabled = state.page <= 1;
  }

  for (const button of document.querySelectorAll('[data-page-action="next"]')) {
    button.disabled = state.page >= totalPages;
  }
}

function buildPlayerRow(player) {
  const tr = document.createElement("tr");
  const stats = player.historical_stats || {};
  const fixture = getFixture(player);
  const playerId = String(player.id);

  tr.append(
    buildSaveCell(
      playerId,
      "team",
      state.myTeam.has(playerId),
      "✓",
      "Add/remove from my team",
      "team-toggle"
    )
  );

  tr.append(
    buildSaveCell(
      playerId,
      "watchlist",
      state.watchlist.has(playerId),
      "★",
      "Add/remove from watchlist",
      "watch-toggle"
    )
  );

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

  appendCell(tr, formatPrice(player.price), "num");
  appendCell(tr, formatPercent(player.selected_pct), "num");

  tr.append(buildStatusCell(player));
  tr.append(buildFixtureCell(fixture));

  appendCell(tr, formatNumber(stats.minutes), "num historic");
  appendCell(tr, formatNumber(stats.fantasy_points), "num historic");
  appendCell(tr, formatNumber(stats.goals), "num historic");
  appendCell(tr, formatNumber(stats.assists), "num historic");
  appendCell(tr, formatNumber(stats.ball_recoveries), "num historic");
  appendCell(tr, formatNumber(stats.player_of_match_awards), "num historic");

  return tr;
}

function buildSaveCell(playerId, listName, active, symbol, title, extraClass) {
  const td = document.createElement("td");
  td.className = "save-cell";

  const button = document.createElement("button");
  button.type = "button";
  button.className = `save-toggle ${extraClass}${active ? " active" : ""}`;
  button.textContent = symbol;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.setAttribute("aria-pressed", active ? "true" : "false");

  button.addEventListener("click", () => {
    const set = listName === "team" ? state.myTeam : state.watchlist;

    if (set.has(playerId)) {
      set.delete(playerId);
    } else {
      set.add(playerId);
    }

    saveLists();
    updateSavedCounts();

    if (els.saved.value) {
      applyFiltersAndSort();
    } else {
      button.classList.toggle("active", set.has(playerId));
      button.setAttribute(
        "aria-pressed",
        set.has(playerId) ? "true" : "false"
      );
    }
  });

  td.append(button);
  return td;
}

function updateSavedCounts() {
  els.teamCount.textContent = state.myTeam.size.toLocaleString();
  els.watchCount.textContent = state.watchlist.size.toLocaleString();
}

function appendCell(tr, value, className = "") {
  const td = document.createElement("td");
  td.textContent = value;
  if (className) td.className = className;
  tr.append(td);
}

function buildStatusCell(player) {
  const td = document.createElement("td");
  const flagged = isFlagged(player);

  const label = flagged
    ? (
        player?.status?.label ||
        player?.status?.code ||
        "Flagged"
      )
    : "Available";

  const pill = document.createElement("span");
  pill.className = `status-pill ${flagged ? "flagged" : "available"}`;
  pill.textContent = label;
  td.append(pill);

  const detail = player?.status?.availability_text;

  if (detail && !isInContentionText(detail)) {
    const small = document.createElement("span");
    small.className = "status-detail";
    small.textContent = detail;
    small.title = detail;
    td.append(small);
  }

  return td;
}

function isInContentionText(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .includes("in contention");
}

function isFlagged(player) {
  const code = String(player?.status?.code || "").trim();
  const text = String(player?.status?.availability_text || "").trim();

  if (code) return true;
  if (!text) return false;
  if (isInContentionText(text)) return false;

  return true;
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

  const opponent = fixture.opponent || fixture.opponent_code || "TBC";
  const location = String(fixture.home_away || "").toUpperCase();

  const locLabel =
    location === "H"
      ? "Home"
      : location === "A"
      ? "Away"
      : location || "";

  const main = document.createElement("span");
  main.className = "fixture-main";
  main.textContent = locLabel ? `${opponent} · ${locLabel}` : opponent;
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

  els.statusMatchday.textContent = meta?.current_matchday ?? "—";
  els.statusPlayers.textContent =
    counts.players ?? playersPayload.count ?? state.players.length;

  const activeMatched = nationality.active_matched_players;
  const activePlayers = nationality.active_players;

  els.statusNationality.textContent =
    activeMatched !== undefined && activePlayers !== undefined
      ? `${activeMatched}/${activePlayers}`
      : `${nationality.matched_players ?? "—"}`;

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
  if (value === "cached_last_known_good") return "cached";
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
  return number === null ? "—" : `€${number.toFixed(1)}m`;
}

function formatPercent(value) {
  const number = numberOrNull(value);
  return number === null
    ? "—"
    : `${number.toFixed(Number.isInteger(number) ? 0 : 1)}%`;
}

function formatNumber(value) {
  const number = numberOrNull(value);
  return number === null ? "—" : number.toLocaleString();
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

function scrollTableIntoView() {
  document.querySelector(".table-panel")?.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

function exportCsv(players, filename) {
  const headers = [
    "UEFA Player ID",
    "Player",
    "Club",
    "Nationality",
    "Position",
    "Price",
    "Selected %",
    "Active",
    "Status",
    "Availability text",
    "On my team",
    "Watchlist",
    "Fixture",
    "2025/26 Minutes",
    "2025/26 Points",
    "2025/26 Goals",
    "2025/26 Assists",
    "2025/26 Ball Recoveries",
    "2025/26 POTM",
  ];

  const rows = players.map((player) => {
    const stats = player.historical_stats || {};
    const id = String(player.id);

    return [
      id,
      player.name || "",
      player?.team?.name || "",
      player?.nationality?.code || "",
      player.position || "",
      numberOrNull(player.price) ?? "",
      numberOrNull(player.selected_pct) ?? "",
      player.active ? "Yes" : "No",
      isFlagged(player)
        ? (player?.status?.label || player?.status?.code || "Flagged")
        : "Available",
      player?.status?.availability_text || "",
      state.myTeam.has(id) ? "Yes" : "No",
      state.watchlist.has(id) ? "Yes" : "No",
      fixtureLabel(player),
      stats.minutes ?? "",
      stats.fantasy_points ?? "",
      stats.goals ?? "",
      stats.assists ?? "",
      stats.ball_recoveries ?? "",
      stats.player_of_match_awards ?? "",
    ];
  });

  const csv = [headers, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n");

  const blob = new Blob([csv], {
    type: "text/csv;charset=utf-8;",
  });

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function showFatalError(error) {
  const main = document.querySelector("main");
  const box = document.createElement("div");
  box.className = "notes";
  box.innerHTML = `
    <strong>Could not load UWCL data.</strong>
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
