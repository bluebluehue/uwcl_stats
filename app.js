const DATA_PATH = "data/uwcl/transformed_data.json";
const META_PATH = "data/uwcl/meta.json";
const TEAM_POSITION_PATH = "data/uwcl/team_position_fixture_ratings.json";
const FIXTURES_PATH = "data/uwcl/fixtures.json";

const STORAGE = {
  team: "uwcl-stats-my-team",
  watch: "uwcl-stats-watchlist",
  gkRotation: "uwcl-stats-gk-rotation-risk",
  activeTab: "uwcl-stats-active-tab",
};

const state = {
  all: [],
  filtered: [],
  sortKey: "decision",
  sortDir: "desc",
  page: 1,
  pageSize: 15,
  myTeam: new Set(),
  watch: new Set(),
  teamPosition: null,
  fixtures: null,
  gkRotation: {},
  activeTab: "players",
  tpSortKey: "def_fix",
  tpSortDir: "desc",
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const els = {
  tbody: $("#player-tbody"),
  search: $("#filter-search"),
  club: $("#filter-club"),
  nat: $("#filter-nationality"),
  pos: $("#filter-position"),
  day: $("#filter-day"),
  saved: $("#filter-saved"),
  active: $("#filter-active"),
  flagged: $("#filter-flagged"),
  maxValue: $("#filter-max-value"),
  minDecision: $("#filter-min-decision"),
  minFix: $("#filter-min-fix"),
  minForm: $("#filter-min-form"),
  pageSize: $("#page-size"),
  pageNumbers: $("#page-numbers"),
  showing: $("#showing-text"),
  empty: $("#empty-state"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  loadSaved();

  try {
    const [payload, meta, teamPosition, fixtures] = await Promise.all([
      fetch(DATA_PATH, { cache: "no-store" }).then(checkJson),
      fetch(META_PATH, { cache: "no-store" }).then(checkJson),
      fetch(TEAM_POSITION_PATH, { cache: "no-store" }).then(checkJson),
      fetch(FIXTURES_PATH, { cache: "no-store" }).then(checkJson),
    ]);

    state.all = Array.isArray(payload.players) ? payload.players : [];
    state.teamPosition = teamPosition;
    state.fixtures = fixtures;
    populateFilters();
    bind();
    bindTabs();
    bindTeamPositionBoard();
    bindGkPairings();
    renderHeader(meta);
    apply();
    renderTeamPositionBoard();
    renderGkPairings();
    renderScheduleAdvantage();
  } catch (err) {
    console.error(err);
    els.empty.hidden = false;
    els.empty.textContent = `Could not load player data: ${err.message}`;
  }
}

function checkJson(response) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function loadSaved() {
  state.myTeam = new Set(readArray(STORAGE.team));
  state.watch = new Set(readArray(STORAGE.watch));
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE.gkRotation) || "{}");
    state.gkRotation = parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    state.gkRotation = {};
  }

  const savedTab = localStorage.getItem(STORAGE.activeTab);
  if (["players","team-position","gk-pairings","schedule"].includes(savedTab)) {
    state.activeTab = savedTab;
  }
}

function readArray(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.map(String) : [];
  } catch {
    return [];
  }
}

function saveLists() {
  localStorage.setItem(STORAGE.team, JSON.stringify([...state.myTeam]));
  localStorage.setItem(STORAGE.watch, JSON.stringify([...state.watch]));
}

function populateFilters() {
  addOptions(els.club, unique(state.all.map(p => p["Club"]).filter(Boolean)));
  addOptions(els.nat, unique(state.all.map(p => p["Nationality"]).filter(Boolean)));
  addOptions(els.day, unique(state.all.map(p => p["Next Fixture Day"]).filter(Boolean)));

  const clubs = unique(state.all.map(p => p["Club"]).filter(Boolean));
  if ($("#gk-include-club")) addOptions($("#gk-include-club"), clubs);
  if ($("#gk-exclude-club")) addOptions($("#gk-exclude-club"), clubs);

  const riskPlayer = $("#gk-risk-player");
  if (riskPlayer) {
    const keepers = state.all
      .filter(p => p.Active && p.Position === "GK")
      .sort((a,b) => String(a.Club).localeCompare(String(b.Club)) || String(a.Name).localeCompare(String(b.Name)));
    for (const gk of keepers) {
      const option = document.createElement("option");
      option.value = String(gk["Player ID"]);
      option.textContent = `${gk.Club} — ${gk.Name}`;
      riskPlayer.append(option);
    }
  }
}

function unique(values) {
  return [...new Set(values)].sort((a, b) => String(a).localeCompare(String(b)));
}

function addOptions(select, values) {
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function bind() {
  const controls = [
    els.search, els.club, els.nat, els.pos, els.day, els.saved,
    els.active, els.flagged, els.maxValue, els.minDecision, els.minFix, els.minForm
  ];

  controls.forEach(control => {
    control.addEventListener(
      control.matches("input[type=search], input[type=number]") ? "input" : "change",
      () => { state.page = 1; apply(); }
    );
  });

  els.pageSize.addEventListener("change", () => {
    state.pageSize = Number(els.pageSize.value) || 15;
    state.page = 1;
    render();
  });

  $("#toggle-key").addEventListener("click", () => {
    $("#key-panel").hidden = !$("#key-panel").hidden;
  });

  $("#reset-filters").addEventListener("click", resetFilters);
  $("#export-view").addEventListener("click", () => exportCsv(state.filtered, "uwcl_current_view.csv"));
  $("#export-all").addEventListener("click", () => exportCsv(state.all, "uwcl_all_players.csv"));

  $$("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      else {
        state.sortKey = key;
        state.sortDir = defaultSortDir(key);
      }
      state.page = 1;
      apply();
    });
  });

  $$("[data-page]").forEach(button => {
    button.addEventListener("click", () => {
      const pages = totalPages();
      const action = button.dataset.page;
      if (action === "first") state.page = 1;
      if (action === "prev") state.page = Math.max(1, state.page - 1);
      if (action === "next") state.page = Math.min(pages, state.page + 1);
      if (action === "last") state.page = pages;
      render();
    });
  });
}

function resetFilters() {
  els.search.value = "";
  els.club.value = "";
  els.nat.value = "";
  els.pos.value = "";
  els.day.value = "";
  els.saved.value = "";
  els.active.checked = true;
  els.flagged.checked = false;
  els.maxValue.value = "";
  els.minDecision.value = "";
  els.minFix.value = "";
  els.minForm.value = "";
  state.page = 1;
  state.sortKey = "decision";
  state.sortDir = "desc";
  apply();
}

function apply() {
  const q = els.search.value.trim().toLowerCase();
  const maxValue = numOrNull(els.maxValue.value);
  const minDecision = numOrNull(els.minDecision.value);
  const minFix = numOrNull(els.minFix.value);
  const minForm = numOrNull(els.minForm.value);

  state.filtered = state.all.filter(p => {
    const id = String(p["Player ID"]);

    if (els.active.checked && !p["Active"]) return false;
    if (els.flagged.checked && !isFlagged(p)) return false;
    if (els.club.value && p["Club"] !== els.club.value) return false;
    if (els.nat.value && p["Nationality"] !== els.nat.value) return false;
    if (els.pos.value && p["Position"] !== els.pos.value) return false;
    if (els.day.value && p["Next Fixture Day"] !== els.day.value) return false;

    if (els.saved.value === "team" && !state.myTeam.has(id)) return false;
    if (els.saved.value === "watchlist" && !state.watch.has(id)) return false;
    if (
      els.saved.value === "either" &&
      !state.myTeam.has(id) &&
      !state.watch.has(id)
    ) return false;

    if (maxValue !== null && Number(p["Value"]) > maxValue) return false;
    if (minDecision !== null && Number(p["Decision Rating"]) < minDecision) return false;
    if (minFix !== null && Number(p["Comparison Fixture Rating"]) < minFix) return false;
    if (minForm !== null && Number(p["Comparison Form Rating"]) < minForm) return false;

    if (q) {
      const haystack = [
        p["Name"], p["Club"], p["Club Name"], p["Nationality"],
        p["Position"], p["Next Fixture Opponent"], p["Next Fixture Opponent Name"]
      ].filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }

    return true;
  });

  state.filtered.sort(compare);
  state.page = Math.min(state.page, totalPages());
  render();
  updateSortIndicators();
}

function updateSortIndicators() {
  $$("th[data-sort]").forEach(th => {
    if (th.dataset.sort === state.sortKey) th.dataset.sortDir = state.sortDir;
    else delete th.dataset.sortDir;
  });
}

function compare(a, b) {
  const av = sortValue(a, state.sortKey);
  const bv = sortValue(b, state.sortKey);

  let result;
  if (typeof av === "number" && typeof bv === "number") result = av - bv;
  else result = String(av ?? "").localeCompare(String(bv ?? ""), undefined, { numeric: true, sensitivity: "base" });

  return state.sortDir === "asc" ? result : -result;
}

function defaultSortDir(key) {
  return ["decision","fix","fix1","form","value","selected","trend","points","p90","ga","br","cs","saves","potm"]
    .includes(key) ? "desc" : "asc";
}

function sortValue(p, key) {
  const map = {
    name: "Name",
    club: "Club",
    nationality: "Nationality",
    day: "Next Fixture Day Number",
    decision: "Decision Rating",
    fix: "Comparison Fixture Rating",
    fix1: "Comparison Following Fixture Rating",
    form: "Comparison Form Rating",
    position: "Position",
    value: "Value",
    selected: "Selected Percentage",
    trend: "Transfer Trend Percentage",
    points: "Previous Season Points",
    p90: "Historical Points Per 90",
    ga: "Total Goals + Assists",
    br: "Total Ball Recoveries",
    cs: "Total Clean Sheets",
    saves: "Total Saves",
    potm: "Total POTM",
  };
  const value = p[map[key]];
  return typeof value === "number" ? value : (value ?? "");
}

function totalPages() {
  return Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
}

function render() {
  els.tbody.innerHTML = "";
  const pages = totalPages();
  state.page = Math.min(Math.max(1, state.page), pages);

  const start = (state.page - 1) * state.pageSize;
  const end = Math.min(start + state.pageSize, state.filtered.length);
  const pageRows = state.filtered.slice(start, end);

  for (const p of pageRows) els.tbody.append(buildRow(p));

  els.empty.hidden = state.filtered.length !== 0;
  $(".table-wrap").hidden = state.filtered.length === 0;

  els.showing.textContent = state.filtered.length
    ? `Showing ${start + 1} to ${end} of ${state.filtered.length} entries`
    : "Showing 0 to 0 of 0 entries";

  renderPages(pages);
  updatePagerButtons(pages);
}

function buildRow(p) {
  const tr = document.createElement("tr");
  const id = String(p["Player ID"]);

  cell(tr, p["Name"] || "—", "player-name sticky-name", statusTitle(p));
  tr.append(saveCell(id, state.myTeam, "🔥", "team"));
  tr.append(saveCell(id, state.watch, "★", "watch"));
  htmlCell(tr, `<span class="club-pill">${esc(p["Club"] || "—")}</span>`);
  cell(tr, p["Nationality"] || "—");
  htmlCell(tr, `<span class="day-pill">${esc(p["Next Fixture Day"] || "—")}</span>`, "", fixtureTitle(p));

  ratingCell(tr, p["Decision Rating"], decisionTitle(p));
  ratingCell(tr, p["Comparison Fixture Rating"], fixtureTitle(p));
  ratingCell(tr, p["Comparison Following Fixture Rating"], followingTitle(p));
  ratingCell(tr, p["Comparison Form Rating"], formTitle(p));
  htmlCell(tr, `<span class="pos-pill">${esc(p["Position"] || "—")}</span>`);
  cell(tr, format1(p["Value"]), "num");
  cell(tr, format1(p["Selected Percentage"]), "num");

  const trend = Number(p["Transfer Trend Percentage"] || 0);
  cell(
    tr,
    `${trend > 0 ? "+" : ""}${format1(trend)}`,
    `num ${trend > 0 ? "delta-pos" : trend < 0 ? "delta-neg" : ""}`,
    "UEFA selected-in percentage minus selected-out percentage; not a historical ownership-change series."
  );

  cell(tr, format0(p["Previous Season Points"]), "num");
  cell(tr, format2(p["Historical Points Per 90"]), "num");
  cell(tr, format0(p["Total Goals + Assists"]), "num");
  cell(tr, format0(p["Total Ball Recoveries"]), "num");
  cell(tr, format0(p["Total Clean Sheets"]), "num");
  cell(tr, format0(p["Total Saves"]), "num");
  cell(tr, format0(p["Total POTM"]), "num");

  return tr;
}

function saveCell(id, set, symbol, kind) {
  const td = document.createElement("td");
  td.className = "save-cell";

  const button = document.createElement("button");
  button.type = "button";
  button.className = `save-toggle ${kind}${set.has(id) ? " active" : ""}`;
  button.textContent = symbol;
  button.title = kind === "team" ? "On my team" : "Watchlist";

  button.addEventListener("click", () => {
    if (set.has(id)) set.delete(id);
    else set.add(id);
    saveLists();

    if (els.saved.value) apply();
    else button.classList.toggle("active", set.has(id));
  });

  td.append(button);
  return td;
}

function cell(tr, value, cls = "", title = "") {
  const td = document.createElement("td");
  td.textContent = value;
  if (cls) td.className = cls;
  if (title) td.title = title;
  tr.append(td);
}

function htmlCell(tr, html, cls = "", title = "") {
  const td = document.createElement("td");
  td.innerHTML = html;
  if (cls) td.className = cls;
  if (title) td.title = title;
  tr.append(td);
}

function ratingCell(tr, value, title = "") {
  const td = document.createElement("td");
  if (value === null || value === undefined || value === "") {
    td.textContent = "—";
  } else {
    const n = Number(value);
    const cls = n >= 85 ? "high" : n >= 70 ? "mid" : n < 50 ? "low" : "";
    td.innerHTML = `<span class="rating-pill ${cls}">${n.toFixed(1)}</span>`;
  }
  if (title) td.title = title;
  tr.append(td);
}

function renderPages(total) {
  els.pageNumbers.innerHTML = "";
  const pages = pageWindow(state.page, total);

  for (const item of pages) {
    if (item === "…") {
      const span = document.createElement("span");
      span.textContent = "…";
      span.style.padding = "0 5px";
      els.pageNumbers.append(span);
      continue;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item;
    if (item === state.page) button.classList.add("active");
    button.addEventListener("click", () => {
      state.page = item;
      render();
    });
    els.pageNumbers.append(button);
  }
}

function pageWindow(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const set = new Set([1, 2, current - 1, current, current + 1, total - 1, total]);
  const nums = [...set].filter(n => n >= 1 && n <= total).sort((a, b) => a - b);
  const out = [];
  nums.forEach((n, i) => {
    if (i && n - nums[i - 1] > 1) out.push("…");
    out.push(n);
  });
  return out;
}

function updatePagerButtons(total) {
  $('[data-page="first"]').disabled = state.page <= 1;
  $('[data-page="prev"]').disabled = state.page <= 1;
  $('[data-page="next"]').disabled = state.page >= total;
  $('[data-page="last"]').disabled = state.page >= total;
}

function isFlagged(p) {
  const code = String(p["Status Code"] || "").trim();
  const text = String(p["Availability Text"] || "").trim().toLowerCase();
  if (code) return true;
  if (!text) return false;
  if (text.includes("in contention")) return false;
  return true;
}

function statusTitle(p) {
  const bits = [];
  if (p["Status Label"]) bits.push(p["Status Label"]);
  if (p["Availability Text"]) bits.push(p["Availability Text"]);
  return bits.join(" — ");
}

function fixtureTitle(p) {
  const d = p["Next Fixture Details"];
  if (!d) return "";
  return [
    `MD${d.matchday}: ${d.opponent_code || d.opponent} (${d.home_away})`,
    `${d.day_short || ""} ${d.date_iso || ""}`,
    `Team Opta: ${d.own_opta_rating ?? "—"} · Opponent Opta: ${d.opponent_opta_rating ?? "—"}`,
    `Strength edge: ${d.opta_strength_edge != null && d.opta_strength_edge > 0 ? "+" : ""}${d.opta_strength_edge ?? "—"}`,
    `Standardized matchup edge: ${d.matchup_standard_score ?? "—"}`,
    `UEFA rank: ${d.opponent_uefa_rank ?? "—"} · coefficient: ${d.opponent_uefa_coefficient ?? "—"}`,
    `Raw provisional fixture rating: ${d.rating ?? "—"}`,
    "Method: own Opta − opponent Opta, standardized across UWCL clubs, then home/away adjustment",
  ].join("\n");
}

function followingTitle(p) {
  const d = p["Following Fixture Details"];
  if (!d) return "";
  return [
    `MD${d.matchday}: ${d.opponent_code || d.opponent} (${d.home_away})`,
    `${d.day_short || ""} ${d.date_iso || ""}`,
    `Team Opta: ${d.own_opta_rating ?? "—"} · Opponent Opta: ${d.opponent_opta_rating ?? "—"}`,
    `Strength edge: ${d.opta_strength_edge != null && d.opta_strength_edge > 0 ? "+" : ""}${d.opta_strength_edge ?? "—"}`,
    `Standardized matchup edge: ${d.matchup_standard_score ?? "—"}`,
    `UEFA rank: ${d.opponent_uefa_rank ?? "—"} · coefficient: ${d.opponent_uefa_coefficient ?? "—"}`,
    `Raw provisional fixture rating: ${d.rating ?? "—"}`,
  ].join("\n");
}

function formTitle(p) {
  return [
    `Raw preseason Form Rating: ${format1(p["Form Rating"])}`,
    `Comparison Form Rating: ${format1(p["Comparison Form Rating"])}`,
    `Confidence: ${format1(Number(p["Form Confidence"] || 0) * 100)}%`,
    p["Form Rating Method"] || "",
  ].join("\n");
}


function decisionTitle(p) {
  return [
    `Decision: ${format1(p["Decision Rating"])}`,
    `Base before availability: ${format1(p["Base Decision Rating Before Availability"])}`,
    `Availability confidence: ${format1(Number(p["Availability Confidence"] || 0) * 100)}%`,
    p["Availability Confidence Note"] || "",
  ].join("\n");
}

function renderHeader(meta) {
  $("#status-matchday").textContent = meta.current_matchday ?? "—";
  $("#status-players").textContent = meta?.counts?.players ?? state.all.length;

  const dt = new Date(meta.fetched_at_utc);
  $("#status-refresh").textContent = Number.isNaN(dt.getTime())
    ? (meta.fetched_at_utc || "")
    : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(dt);

  const feeds = meta.feed_status || {};
  $("#status-feeds").innerHTML = ["players","teams","fixtures"].map(name => {
    const status = feeds[name] || "unknown";
    const cls = status === "live" ? "live" : "";
    const label = status === "cached_last_known_good" ? "cached" : status;
    return `<span class="feed-chip ${cls}">${name}: ${label}</span>`;
  }).join("");
}

function exportCsv(rows, filename) {
  const keys = [
    "Player ID","Name","Club","Club Name","Nationality","Next Fixture Day",
    "Decision Rating","Comparison Fixture Rating","Comparison Following Fixture Rating",
    "Comparison Form Rating","Comparison Involvement Rating","Position","Value",
    "Selected Percentage","Transfer Trend Percentage","Previous Season Points",
    "Historical Points Per 90","Total Goals","Total Assists","Total Goals + Assists",
    "Total Ball Recoveries","Total Clean Sheets","Total Saves","Total POTM"
  ];

  const data = [keys, ...rows.map(p => keys.map(k => p[k] ?? ""))]
    .map(row => row.map(csvCell).join(","))
    .join("\r\n");

  const blob = new Blob([data], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvCell(v) {
  return `"${String(v ?? "").replaceAll('"', '""')}"`;
}

function numOrNull(v) {
  if (v === "" || v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function format0(v) { return v == null ? "—" : Number(v).toFixed(0); }
function format1(v) { return v == null ? "—" : Number(v).toFixed(1); }
function format2(v) { return v == null ? "—" : Number(v).toFixed(2); }
function esc(v) {
  return String(v ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;")
    .replaceAll(">","&gt;").replaceAll('"',"&quot;");
}


function activateTab(target, persist = true) {
  if (!["players","team-position","gk-pairings","schedule"].includes(target)) target = "players";

  state.activeTab = target;
  $$(".tab").forEach(button => {
    button.classList.toggle("active", button.dataset.tab === target);
  });
  $$(".tab-panel").forEach(panel => {
    panel.classList.toggle("active", panel.id === `panel-${target}`);
  });

  if (persist) localStorage.setItem(STORAGE.activeTab, target);
}

function bindTabs() {
  $$(".tab").forEach(button => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });

  activateTab(state.activeTab, false);
}

function bindTeamPositionBoard() {
  $("#tp-position")?.addEventListener("change", renderTeamPositionBoard);

  $$("th[data-tp-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.tpSort;
      if (state.tpSortKey === key) {
        state.tpSortDir = state.tpSortDir === "asc" ? "desc" : "asc";
      } else {
        state.tpSortKey = key;
        state.tpSortDir = key === "club" || key === "fixture" ? "asc" : "desc";
      }
      renderTeamPositionBoard();
    });
  });
}

function scoreClass(value) {
  const n = Number(value);
  if (n >= 80) return "tp-great";
  if (n >= 65) return "tp-good";
  if (n >= 50) return "tp-mid";
  return "tp-bad";
}

function scoreHtml(value) {
  if (value == null) return "—";
  return `<span class="tp-score ${scoreClass(value)}">${Number(value).toFixed(1)}</span>`;
}

function updateTeamPositionSortIndicators() {
  $$("th[data-tp-sort]").forEach(th => {
    if (th.dataset.tpSort === state.tpSortKey) th.dataset.sortDir = state.tpSortDir;
    else delete th.dataset.sortDir;
  });
}

function teamPositionSortValue(team, key, wantedPos) {
  const f = team.fixture || {};
  const positions = team.positions || {};

  if (key === "club") return String(team.club_name || team.club || "");
  if (key === "fixture") return String(f.opponent_code || f.opponent || "");

  const map = {
    gk_fix: ["GK", "current"],
    gk_fix1: ["GK", "following"],
    def_fix: ["DEF", "current"],
    def_fix1: ["DEF", "following"],
    mid_fix: ["MID", "current"],
    mid_fix1: ["MID", "following"],
    fwd_fix: ["FWD", "current"],
    fwd_fix1: ["FWD", "following"],
  };

  if (map[key]) {
    const [pos, horizon] = map[key];
    if (wantedPos && wantedPos !== pos) return -999;
    return positions[pos]?.[horizon] ?? -999;
  }

  return -999;
}

function compareTeamPosition(a, b, key, dir, wantedPos) {
  const av = teamPositionSortValue(a, key, wantedPos);
  const bv = teamPositionSortValue(b, key, wantedPos);
  let cmp = 0;

  if (typeof av === "string" || typeof bv === "string") {
    cmp = String(av).localeCompare(String(bv));
  } else {
    cmp = Number(av) - Number(bv);
  }

  if (cmp === 0) {
    cmp = String(a.club_name || a.club || "").localeCompare(String(b.club_name || b.club || ""));
  }

  return dir === "asc" ? cmp : -cmp;
}

function renderTeamPositionBoard() {
  const tbody = $("#team-position-tbody");
  if (!tbody || !state.teamPosition) return;

  const wantedPos = $("#tp-position")?.value || "";
  let teams = [...(state.teamPosition.teams || [])];

  teams.sort((a,b) => compareTeamPosition(a, b, state.tpSortKey, state.tpSortDir, wantedPos));
  updateTeamPositionSortIndicators();

  tbody.innerHTML = "";

  for (const team of teams) {
    const tr = document.createElement("tr");
    const f = team.fixture || {};
    const positions = team.positions || {};

    const fixtureText = `${f.opponent_code || f.opponent || "—"} ${f.home_away ? `(${f.home_away})` : ""}`;

    const cellFor = (pos, horizon) => {
      if (wantedPos && wantedPos !== pos) return "—";
      return scoreHtml(positions[pos]?.[horizon]);
    };

    tr.innerHTML = `
      <td><strong>${esc(team.club_name || team.club || "—")}</strong></td>
      <td class="fixture-cell">
        ${esc(fixtureText)}
        <small>${esc(f.day_short || "")} · Team ${f.own_opta_rating ?? "—"} / Opp ${f.opponent_opta_rating ?? "—"}</small>
      </td>

      <td>${cellFor("GK", "current")}</td>
      <td class="secondary-score">${cellFor("GK", "following")}</td>

      <td>${cellFor("DEF", "current")}</td>
      <td class="secondary-score">${cellFor("DEF", "following")}</td>

      <td>${cellFor("MID", "current")}</td>
      <td class="secondary-score">${cellFor("MID", "following")}</td>

      <td>${cellFor("FWD", "current")}</td>
      <td class="secondary-score">${cellFor("FWD", "following")}</td>
    `;
    tbody.append(tr);
  }
}

function bindGkPairings() {
  $("#gk-max-price")?.addEventListener("input", renderGkPairings);
  $("#gk-hide-high-rotation")?.addEventListener("change", renderGkPairings);
  $("#gk-include-club")?.addEventListener("change", renderGkPairings);
  $("#gk-exclude-club")?.addEventListener("change", renderGkPairings);
  $("#gk-sort")?.addEventListener("change", renderGkPairings);

  $$(".gk-md-toggle").forEach(cb => {
    cb.addEventListener("change", () => {
      ensureAtLeastOneSelectedMatchday(cb);
      syncMatchdayRange();
      renderGkPairings();
    });
  });

  $("#gk-md-all")?.addEventListener("click", () => {
    $$(".gk-md-toggle").forEach(cb => { cb.checked = true; });
    syncMatchdayRange();
    renderGkPairings();
  });

  $("#gk-min-splits")?.addEventListener("input", () => {
    const value = Number($("#gk-min-splits").value || 0);
    $("#gk-min-splits-value").textContent = `${value}/6`;
    renderGkPairings();
  });

  $("#gk-risk-player")?.addEventListener("change", syncRotationEditor);
  $("#gk-risk-level")?.addEventListener("change", saveRotationRisk);
}

function selectedMatchdays() {
  const selected = $$(".gk-md-toggle")
    .filter(cb => cb.checked)
    .map(cb => Number(cb.value))
    .filter(md => md >= 1 && md <= 6);

  return selected.length ? selected.sort((a,b) => a-b) : [1];
}

function ensureAtLeastOneSelectedMatchday(changedBox) {
  const checked = $$(".gk-md-toggle").filter(cb => cb.checked);
  if (!checked.length && changedBox) changedBox.checked = true;
}

function syncMatchdayRange() {
  const mds = selectedMatchdays();
  const slider = $("#gk-min-splits");
  const label = $("#gk-min-splits-value");
  const header = $("#gk-best-fix-header");
  if (slider) {
    slider.max = String(mds.length);
    if (Number(slider.value) > mds.length) slider.value = String(mds.length);
  }
  if (label) label.textContent = `${slider ? Number(slider.value || 0) : 0}/${mds.length}`;
  if (header) header.textContent = `BEST FIX (${mds.length} MD${mds.length === 1 ? "" : "S"})`;
}

function syncRotationEditor() {
  const playerId = $("#gk-risk-player")?.value || "";
  const level = playerId ? (state.gkRotation[playerId] || "none") : "none";
  if ($("#gk-risk-level")) $("#gk-risk-level").value = level;
}

function saveRotationRisk() {
  const playerId = $("#gk-risk-player")?.value || "";
  if (!playerId) return;

  const level = $("#gk-risk-level")?.value || "none";
  if (level === "none") delete state.gkRotation[playerId];
  else state.gkRotation[playerId] = level;

  localStorage.setItem(STORAGE.gkRotation, JSON.stringify(state.gkRotation));
  renderGkPairings();
}

function rotationRisk(player) {
  return state.gkRotation[String(player["Player ID"])] || "none";
}

function rotationRiskLabel(player) {
  const risk = rotationRisk(player);
  if (risk === "high") return " ⚠";
  if (risk === "possible") return " ◇";
  return "";
}

function shortWeekdayFromKickoff(kickoff) {
  if (!kickoff) return "";
  const d = new Date(kickoff);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    timeZone: "Europe/London",
  }).toUpperCase();
}

function clubScheduleMap() {
  const byClub = new Map();

  // Seed the clubs from player data so naming stays consistent with the rest of the site.
  for (const player of state.all) {
    if (!player.Active || !player.Club || byClub.has(player.Club)) continue;
    byClub.set(player.Club, {
      club: player.Club,
      clubName: player["Club Name"] || player.Club,
      teamId: String(player["Team ID"] || ""),
      days: {},
      fixtureRatings: {},
      currentFix: Number(player["Comparison Fixture Rating"] || 0),
    });
  }

  // Primary source for GK split-day coverage: the normalized six-matchday
  // fixtures file itself. This avoids depending on a derived player field.
  const matches = Array.isArray(state.fixtures?.matches) ? state.fixtures.matches : [];

  for (const match of matches) {
    const md = Number(match?.matchday || 0);
    if (md < 1 || md > 6) continue;

    const day = shortWeekdayFromKickoff(match?.kickoff);
    if (!day) continue;

    const homeCode = String(match?.home?.code || "");
    const awayCode = String(match?.away?.code || "");
    const homeId = String(match?.home?.id || "");
    const awayId = String(match?.away?.id || "");

    for (const entry of byClub.values()) {
      if (
        (homeCode && entry.club === homeCode) ||
        (homeId && entry.teamId === homeId)
      ) {
        entry.days[md] = day;
      }

      if (
        (awayCode && entry.club === awayCode) ||
        (awayId && entry.teamId === awayId)
      ) {
        entry.days[md] = day;
      }
    }
  }

  // Backward-compatible fallback for any club whose fixture feed did not map.
  // Older transformed_data versions may or may not contain this field.
  for (const player of state.all) {
    if (!player.Active || !player.Club) continue;
    const entry = byClub.get(player.Club);
    if (!entry) continue;

    const fixtures = player["League Phase Fixtures"] || [];
    for (const fixture of fixtures) {
      const md = Number(fixture?.matchday || 0);
      if (md < 1 || md > 6) continue;

      if (!entry.days[md]) {
        entry.days[md] = fixture.day_short || "";
      }

      if (fixture?.rating != null && entry.fixtureRatings[md] == null) {
        entry.fixtureRatings[md] = Number(fixture.rating);
      }
    }
  }

  return byClub;
}
function keepersByClub() {
  const map = new Map();

  for (const player of state.all) {
    if (!player.Active || player.Position !== "GK" || !player.Club) continue;
    if (!map.has(player.Club)) map.set(player.Club, []);
    map.get(player.Club).push(player);
  }

  for (const [, keepers] of map) {
    keepers.sort((a,b) => {
      const priority = role => role === "Starter" ? 0 : role === "Likely starter" ? 1 : role === "Uncertain" ? 2 : 3;
      return priority(a["GK Role"]) - priority(b["GK Role"])
        || Number(b["Previous Season Minutes"] || 0) - Number(a["Previous Season Minutes"] || 0);
    });
  }

  return map;
}

function primaryKeeperForClub(club, keeperMap) {
  const keepers = keeperMap.get(club) || [];
  return keepers.find(p => p["GK Role"] === "Starter")
    || keepers.find(p => p["GK Role"] === "Likely starter")
    || keepers.find(p => p["GK Role"] === "Uncertain")
    || keepers[0]
    || null;
}

function splitCoverage(daysA, daysB, selectedMds) {
  let split = 0;
  const details = [];
  const selectedSet = new Set(selectedMds);
  for (let md=1; md<=6; md++) {
    const a = daysA[md] || "";
    const b = daysB[md] || "";
    const selected = selectedSet.has(md);
    const isSplit = Boolean(selected && a && b && a !== b);
    if (isSplit) split++;
    details.push({md, a, b, split: isSplit, selected});
  }
  return {split, details};
}

function normalizeFixtureRating(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  // Current raw fixture model is intentionally bounded to 20–85.
  return Math.max(0, Math.min(100, ((n - 20) / 65) * 100));
}

function pairScoreFromMetrics(selectedFix, splitCount, selectedCount) {
  if (!selectedFix || selectedFix.average == null || selectedFix.floor == null) return null;
  const avgNorm = normalizeFixtureRating(selectedFix.average);
  const floorNorm = normalizeFixtureRating(selectedFix.floor);
  const denominator = Math.max(1, Number(selectedCount || 1));
  const splitNorm = Math.max(0, Math.min(100, (Number(splitCount || 0) / denominator) * 100));
  if (avgNorm == null || floorNorm == null) return null;
  return 0.60 * avgNorm + 0.20 * floorNorm + 0.20 * splitNorm;
}

function pairFixtureMetric(a, b, selectedMds) {
  const weeklyBest = [];
  for (const md of selectedMds) {
    const ar = Number(a?.fixtureRatings?.[md]);
    const br = Number(b?.fixtureRatings?.[md]);
    const validA = Number.isFinite(ar);
    const validB = Number.isFinite(br);
    if (validA && validB) weeklyBest.push(Math.max(ar, br));
    else if (validA) weeklyBest.push(ar);
    else if (validB) weeklyBest.push(br);
  }
  if (!weeklyBest.length) return {average: null, floor: null, weeklyBest: []};
  return {average: weeklyBest.reduce((sum, x) => sum + x, 0) / weeklyBest.length, floor: Math.min(...weeklyBest), weeklyBest};
}

function dayChip(detail, pair) {
  const aDay = detail.a || "—";
  const bDay = detail.b || "—";

  const aFix = Number(pair?.a?.fixtureRatings?.[detail.md]);
  const bFix = Number(pair?.b?.fixtureRatings?.[detail.md]);

  const validA = Number.isFinite(aFix);
  const validB = Number.isFinite(bFix);

  let better = "";
  if (validA && validB) {
    if (aFix > bFix) better = "a";
    else if (bFix > aFix) better = "b";
  } else if (validA) {
    better = "a";
  } else if (validB) {
    better = "b";
  }

  const line = (club, score, which) => {
    const cls = better === which ? "md-option best" : "md-option";
    return `<div class="${cls}"><span>${esc(club)}</span><strong>${Number.isFinite(score) ? score.toFixed(1) : "—"}</strong></div>`;
  };

  const splitCls = detail.split ? "md-schedule split" : "md-schedule same";
  const splitSymbol = detail.split ? "✓" : "×";

  return `
    <div class="md-cell ${detail.selected ? "selected-md" : "unselected-md"}">
      ${line(pair.clubA, aFix, "a")}
      ${line(pair.clubB, bFix, "b")}
      <div class="${splitCls}">${esc(aDay)} / ${esc(bDay)} ${splitSymbol}</div>
    </div>
  `;
}


function keeperDetail(player) {
  if (!player) return `<span class="gk-secondary">Starter unclear</span>`;

  const price = Number(player.Value || 0).toFixed(1);
  const role = player["GK Role"] || "Uncertain";
  const risk = rotationRiskLabel(player);

  return `
    <span class="gk-name">${esc(player.Name)}${esc(risk)}</span>
    <span class="gk-secondary">${esc(role)} · €${price}</span>
  `;
}

function pairPrice(a, b) {
  if (!a || !b) return null;
  return Number(a.Value || 0) + Number(b.Value || 0);
}

function renderGkPairings() {
  const tbody = $("#gk-pairing-tbody");
  if (!tbody) return;

  const selectedMds = selectedMatchdays();
  syncMatchdayRange();
  const minSplits = Number($("#gk-min-splits")?.value || 0);
  const includeClub = $("#gk-include-club")?.value || "";
  const excludeClub = $("#gk-exclude-club")?.value || "";
  const maxCombined = numOrNull($("#gk-max-price")?.value);
  const hideHighRotation = $("#gk-hide-high-rotation")?.checked ?? false;
  const sortMode = $("#gk-sort")?.value || "pair_score";

  const clubMap = clubScheduleMap();
  const keeperMap = keepersByClub();
  const clubs = [...clubMap.keys()].sort();
  const pairs = [];

  for (let i=0; i<clubs.length; i++) {
    for (let j=i+1; j<clubs.length; j++) {
      const clubA = clubs[i], clubB = clubs[j];

      if (includeClub && clubA !== includeClub && clubB !== includeClub) continue;
      if (excludeClub && (clubA === excludeClub || clubB === excludeClub)) continue;

      const a = clubMap.get(clubA);
      const b = clubMap.get(clubB);
      const coverage = splitCoverage(a.days, b.days, selectedMds);
      if (coverage.split < minSplits) continue;

      const gkA = primaryKeeperForClub(clubA, keeperMap);
      const gkB = primaryKeeperForClub(clubB, keeperMap);
      const combined = pairPrice(gkA, gkB);

      if (maxCombined !== null && combined !== null && combined > maxCombined) continue;
      if (hideHighRotation && (
        (gkA && rotationRisk(gkA) === "high") ||
        (gkB && rotationRisk(gkB) === "high")
      )) continue;

      const sixMdFix = pairFixtureMetric(a, b, selectedMds);
      const pairScore = pairScoreFromMetrics(sixMdFix, coverage.split, selectedMds.length);

      pairs.push({
        clubA, clubB, a, b,
        gkA, gkB, combined,
        split: coverage.split,
        details: coverage.details,
        sixMdFix,
        pairScore,
        currentFix: (Number(a.currentFix || 0) + Number(b.currentFix || 0)) / 2,
      });
    }
  }

  pairs.sort((x,y) => {
    const nameCmp = `${x.clubA}-${x.clubB}`.localeCompare(`${y.clubA}-${y.clubB}`);

    if (sortMode === "best_fix") {
      return ((y.sixMdFix.average ?? -999) - (x.sixMdFix.average ?? -999))
        || ((y.sixMdFix.floor ?? -999) - (x.sixMdFix.floor ?? -999))
        || (y.split - x.split)
        || nameCmp;
    }

    if (sortMode === "floor") {
      return ((y.sixMdFix.floor ?? -999) - (x.sixMdFix.floor ?? -999))
        || ((y.sixMdFix.average ?? -999) - (x.sixMdFix.average ?? -999))
        || (y.split - x.split)
        || nameCmp;
    }

    if (sortMode === "split") {
      return (y.split - x.split)
        || ((y.sixMdFix.average ?? -999) - (x.sixMdFix.average ?? -999))
        || nameCmp;
    }

    if (sortMode === "current_fix") {
      return (y.currentFix - x.currentFix)
        || ((y.pairScore ?? -999) - (x.pairScore ?? -999))
        || nameCmp;
    }

    if (sortMode === "price") {
      return ((x.combined ?? 999) - (y.combined ?? 999))
        || ((y.pairScore ?? -999) - (x.pairScore ?? -999))
        || nameCmp;
    }

    // Default: Pair Score
    return ((y.pairScore ?? -999) - (x.pairScore ?? -999))
      || ((y.sixMdFix.average ?? -999) - (x.sixMdFix.average ?? -999))
      || (y.split - x.split)
      || nameCmp;
  });

  const summary = $("#gk-summary");
  if (summary) {
    const anchorText = includeClub ? ` containing ${includeClub}` : "";
    const sortLabels = {
      pair_score: "Pair Score",
      best_fix: "6-MD Best Fix",
      floor: "Fixture Floor",
      split: "Split Coverage",
      current_fix: "Current FIX",
      price: "Lowest Price",
    };
    const mdLabel = selectedMds.map(md => `MD${md}`).join(", ");
    summary.innerHTML = `<strong>${pairs.length}</strong> club pair${pairs.length === 1 ? "" : "s"}${esc(anchorText)} meet the current filters for <strong>${esc(mdLabel)}</strong>. Sorted by ${esc(sortLabels[sortMode] || "Pair Score")}.`;
  }

  tbody.innerHTML = "";

  for (const pair of pairs) {
    const tr = document.createElement("tr");
    const coveragePct = Math.round(pair.split / selectedMds.length * 100);

    tr.innerHTML = `
      <td class="club-pair-cell">
        <strong>${esc(pair.clubA)} + ${esc(pair.clubB)}</strong>
        <span class="gk-secondary">${esc(pair.a.clubName)} / ${esc(pair.b.clubName)}</span>
      </td>

      <td class="pair-score-cell" title="60% selected-matchday best-fixture quality · 20% selected-matchday fixture floor · 20% split-day coverage">
        <strong>${pair.pairScore == null ? "—" : pair.pairScore.toFixed(1)}</strong>
      </td>

      <td class="coverage-col">
        <div class="coverage-score">${pair.split}/${selectedMds.length}</div>
        <div class="coverage-bar"><span style="width:${coveragePct}%"></span></div>
      </td>

      <td title="Average of the stronger GK fixture available across the selected matchdays. Floor = weakest of those selected best-available fixtures.">
        <strong>${pair.sixMdFix.average == null ? "—" : pair.sixMdFix.average.toFixed(1)}</strong>
        <span class="gk-secondary">floor ${pair.sixMdFix.floor == null ? "—" : pair.sixMdFix.floor.toFixed(1)}</span>
      </td>

      ${pair.details.map(detail => `<td>${dayChip(detail, pair)}</td>`).join("")}

      <td class="keeper-pair-cell">
        <div>${keeperDetail(pair.gkA)}</div>
        <div>${keeperDetail(pair.gkB)}</div>
      </td>

      <td>${pair.combined == null ? "—" : `€${pair.combined.toFixed(1)}`}</td>
      <td>${pair.currentFix.toFixed(1)}</td>
    `;

    tbody.append(tr);
  }

  if (!pairs.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="13" class="empty-state">No club pairs match these filters.</td>`;
    tbody.append(tr);
  }
}


function utcDateKey(kickoff) {
  if (!kickoff) return "";
  const d = new Date(kickoff);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 10);
}

function utcMinutesOfDay(kickoff) {
  if (!kickoff) return null;
  const d = new Date(kickoff);
  if (Number.isNaN(d.getTime())) return null;
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

function easternKickoffLabel(kickoff) {
  if (!kickoff) return "";
  const d = new Date(kickoff);
  if (Number.isNaN(d.getTime())) return "";

  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);

  const hour = Number(parts.find(p => p.type === "hour")?.value);
  const minute = Number(parts.find(p => p.type === "minute")?.value);

  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return "";

  // UWCL league-phase kickoff slots are 12:45 PM ET and 3:00 PM ET
  // for MD1–5. MD6 is simultaneous, but classifying 3:00 PM as late
  // remains harmless for display.
  if (hour === 12 && minute === 45) return "EARLY";
  if (hour === 15 && minute === 0) return "LATE";

  // Defensive fallback for equivalent timestamps if DST/formatting shifts:
  // anything before 14:00 ET is the early slot; otherwise late.
  const mins = hour * 60 + minute;
  return mins < 14 * 60 ? "EARLY" : "LATE";
}

function buildScheduleAdvantageRows() {
  const matches = Array.isArray(state.fixtures?.matches) ? state.fixtures.matches : [];
  const clubs = new Map();

  // Seed all 18 clubs from player data so every fantasy club appears.
  for (const p of state.all) {
    if (!p.Active || !p.Club || clubs.has(p.Club)) continue;
    clubs.set(p.Club, {
      club: p.Club,
      name: p["Club Name"] || p.Club,
      teamId: String(p["Team ID"] || ""),
      matchdays: {},
    });
  }

  const byMd = new Map();
  for (const match of matches) {
    const md = Number(match?.matchday || 0);
    if (md < 1 || md > 6) continue;
    if (!byMd.has(md)) byMd.set(md, []);
    byMd.get(md).push(match);
  }

  for (let md = 1; md <= 6; md++) {
    const mdMatches = byMd.get(md) || [];

    // UEFA's normalized feed already preserves the fantasy game-day id (gdId).
    // Each league-phase matchweek has exactly two fantasy game-days.
    // Use that instead of deriving D1/D2 from calendar dates.
    const gdIds = [...new Set(
      mdMatches
        .map(m => Number(m?.fantasy_gameday_id))
        .filter(v => Number.isFinite(v) && v > 0)
    )].sort((a,b) => a-b);

    // Fallback only if gdId is unexpectedly missing.
    const dates = [...new Set(
      mdMatches.map(m => utcDateKey(m?.kickoff)).filter(Boolean)
    )].sort();

    for (const match of mdMatches) {
      const gdId = Number(match?.fantasy_gameday_id);

      let dayNumber;
      if (Number.isFinite(gdId) && gdIds.includes(gdId)) {
        dayNumber = gdIds.indexOf(gdId) + 1;
      } else {
        const dateKey = utcDateKey(match?.kickoff);
        dayNumber = Math.min(2, Math.max(1, dates.indexOf(dateKey) + 1));
      }

      // Defensive guard: there are only two days in each league-phase matchweek.
      dayNumber = dayNumber === 2 ? 2 : 1;

      const kickoffSlot = easternKickoffLabel(match?.kickoff);
      const isEarly = kickoffSlot === "EARLY";

      const homeCode = String(match?.home?.code || "");
      const awayCode = String(match?.away?.code || "");
      const homeId = String(match?.home?.id || "");
      const awayId = String(match?.away?.id || "");

      for (const entry of clubs.values()) {
        let homeAway = "";
        let opponent = "";

        if (
          (homeCode && entry.club === homeCode) ||
          (homeId && entry.teamId === homeId)
        ) {
          homeAway = "H";
          opponent = awayCode || String(match?.away?.name || "");
        } else if (
          (awayCode && entry.club === awayCode) ||
          (awayId && entry.teamId === awayId)
        ) {
          homeAway = "A";
          opponent = homeCode || String(match?.home?.name || "");
        } else {
          continue;
        }

        entry.matchdays[md] = {
          day: dayNumber,
          early: isEarly,
          kickoffSlot,
          opponent,
          homeAway,
        };
      }
    }
  }

  return [...clubs.values()]
    .map(entry => {
      let day1Count = 0;
      let earlyCount = 0;
      let bothCount = 0;

      for (let md = 1; md <= 6; md++) {
        const x = entry.matchdays[md];
        if (!x) continue;
        if (x.day === 1) day1Count++;
        if (x.early) earlyCount++;
        if (x.day === 1 && x.early) bothCount++;
      }

      return {...entry, day1Count, earlyCount, bothCount};
    })
    .sort((a,b) =>
      (b.bothCount - a.bothCount) ||
      (b.day1Count - a.day1Count) ||
      (b.earlyCount - a.earlyCount) ||
      a.name.localeCompare(b.name)
    );
}
function scheduleCellHtml(item) {
  if (!item) return `<span class="schedule-empty">—</span>`;

  const cls =
    item.day === 1 && item.early ? "both" :
    item.day === 1 ? "day1" :
    item.early ? "early" : "neutral";

  const slot = item.early ? "EARLY" : "LATE";
  const opp = item.opponent
    ? `${item.homeAway === "A" ? "@" : "vs"} ${item.opponent}`
    : "";

  return `
    <div class="schedule-cell">
      <span class="schedule-chip ${cls}">D${item.day} · ${slot}</span>
      <small>${esc(opp)}</small>
    </div>
  `;
}

function renderScheduleAdvantage() {
  const tbody = $("#schedule-tbody");
  if (!tbody) return;

  const rows = buildScheduleAdvantageRows();
  tbody.innerHTML = "";

  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="schedule-sticky-club">
        <strong>${esc(row.name)}</strong>
        <small>${esc(row.club)}</small>
      </td>
      ${[1,2,3,4,5,6].map(md => `<td>${scheduleCellHtml(row.matchdays[md])}</td>`).join("")}
      <td class="schedule-count">${row.day1Count}/6</td>
      <td class="schedule-count">${row.earlyCount}/6</td>
      <td class="schedule-count schedule-count-strong">${row.bothCount}/6</td>
    `;
    tbody.append(tr);
  }

  const summary = $("#schedule-summary");
  if (summary) {
    const topBoth = rows.length ? Math.max(...rows.map(r => r.bothCount)) : 0;
    const leaders = rows.filter(r => r.bothCount === topBoth).map(r => r.club).join(", ");
    summary.innerHTML = `<strong>${rows.length}</strong> clubs across MD1–6. Best D1 + early coverage: <strong>${topBoth}/6</strong>${leaders ? ` (${esc(leaders)})` : ""}.`;
  }
}
