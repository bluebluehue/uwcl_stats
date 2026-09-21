const DATA_PATH = "data/uwcl/transformed_data.json";
const META_PATH = "data/uwcl/meta.json";

const STORAGE = {
  team: "uwcl-stats-my-team",
  watch: "uwcl-stats-watchlist",
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
    const [payload, meta] = await Promise.all([
      fetch(DATA_PATH, { cache: "no-store" }).then(checkJson),
      fetch(META_PATH, { cache: "no-store" }).then(checkJson),
    ]);

    state.all = Array.isArray(payload.players) ? payload.players : [];
    populateFilters();
    bind();
    renderHeader(meta);
    apply();
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
  return ["decision","fix","fix1","form","inv","value","selected","trend","points","p90","ga","br","cs","saves","potm"]
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
    inv: "Comparison Involvement Rating",
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

  tr.append(saveCell(id, state.myTeam, "🔥", "team"));
  tr.append(saveCell(id, state.watch, "★", "watch"));

  cell(tr, p["Name"] || "—", "player-name", statusTitle(p));
  htmlCell(tr, `<span class="club-pill">${esc(p["Club"] || "—")}</span>`);
  cell(tr, p["Nationality"] || "—");
  htmlCell(tr, `<span class="day-pill">${esc(p["Next Fixture Day"] || "—")}</span>`, "", fixtureTitle(p));

  ratingCell(tr, p["Decision Rating"], decisionTitle(p));
  ratingCell(tr, p["Comparison Fixture Rating"], fixtureTitle(p));
  ratingCell(tr, p["Comparison Following Fixture Rating"], followingTitle(p));
  ratingCell(tr, p["Comparison Form Rating"], formTitle(p));
  ratingCell(tr, p["Comparison Involvement Rating"], involvementTitle(p));

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
    `Opponent ${d.opponent_pot || "pot unknown"}`,
    `Raw provisional fixture rating: ${d.rating ?? "—"}`,
    "Method: opponent draw pot + home/away adjustment",
  ].join("\n");
}

function followingTitle(p) {
  const d = p["Following Fixture Details"];
  if (!d) return "";
  return [
    `MD${d.matchday}: ${d.opponent_code || d.opponent} (${d.home_away})`,
    `${d.day_short || ""} ${d.date_iso || ""}`,
    `Opponent ${d.opponent_pot || "pot unknown"}`,
    `Raw provisional fixture rating: ${d.rating ?? "—"}`,
  ].join("\n");
}

function formTitle(p) {
  return [
    `Raw Form Rating: ${format1(p["Form Rating"])}`,
    `Comparison Form Rating: ${format1(p["Comparison Form Rating"])}`,
    `Confidence: ${format1(Number(p["Form Confidence"] || 0) * 100)}%`,
    p["Form Rating Method"] || "",
  ].join("\n");
}

function involvementTitle(p) {
  if (p["Comparison Involvement Rating"] == null) {
    return p["Player Involvement Method"] || "No involvement rating.";
  }
  return [
    `Raw involvement: ${format1(p["Player Involvement Rating"])}`,
    `Comparison involvement: ${format1(p["Comparison Involvement Rating"])}`,
    `Confidence: ${format1(Number(p["Player Involvement Confidence"] || 0) * 100)}%`,
    p["Player Involvement Method"] || "",
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
