/* Scoreboard client.
 *
 * The delay lives here, not on the server: it is sent with each request and
 * persisted to localStorage. That keeps the server stateless and lets the table
 * screen and a phone run different delays if the broadcasts differ.
 */

const REFRESH_MS = 3000;
const DELAY_STEP = 15;
const MAX_DELAY = 900;

function storedDelay() {
  /* null means "no choice saved in this browser yet" - the first request omits
     the delay parameter so the server's configured default applies, and we
     adopt whatever it returns. Hardcoding 120 here made
     default_delay_seconds in config.toml silently do nothing.

     Anything unparseable counts as unset: Number("") is 0, so a blank entry
     would otherwise pin the delay to zero and quietly spoil every fight. */
  const raw = localStorage.getItem("delaySeconds");
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? clampDelay(value) : null;
}

const state = {
  delay: storedDelay(),
  delayFromValve: false,
  wallEnabled: false,
  wallCount: 4,
  activeWallTile: null,
  showDrafts: localStorage.getItem("showDrafts") === "true",
  heroes: {},
};

const el = {
  grid: document.getElementById("grid"),
  status: document.getElementById("status"),
  delayValue: document.getElementById("delay-value"),
  delaySource: document.getElementById("delay-source"),
  delayUp: document.getElementById("delay-up"),
  delayDown: document.getElementById("delay-down"),
  draftToggle: document.getElementById("draft-toggle"),
  hardRefresh: document.getElementById("hard-refresh"),
};

function clampDelay(value) {
  if (!Number.isFinite(value)) return 120;
  return Math.max(0, Math.min(value, MAX_DELAY));
}

function setDelay(seconds) {
  state.delay = clampDelay(seconds);
  // Once you override it by hand it is no longer Valve's number.
  state.delayFromValve = false;
  localStorage.setItem("delaySeconds", String(state.delay));
  renderDelay();
  refresh();
}

function renderDelay() {
  if (state.delay === null) {
    el.delayValue.textContent = "--";
    return;
  }
  const m = Math.floor(state.delay / 60);
  const s = state.delay % 60;
  el.delayValue.textContent = m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
  el.delaySource.textContent = state.delayFromValve
    ? "delay (from Valve)"
    : "broadcast delay";
}

/* "+15s" means "show me newer data", i.e. a SMALLER delay. Labelling these by
   what the viewer wants rather than by the underlying number avoids the
   inverted-control confusion. */
/* Guard against a click landing before the first response has told us what the
   server's default delay is. */
el.delayUp.addEventListener("click", () => {
  if (state.delay !== null) setDelay(state.delay - DELAY_STEP);
});
el.delayDown.addEventListener("click", () => {
  if (state.delay !== null) setDelay(state.delay + DELAY_STEP);
});

el.draftToggle.checked = state.showDrafts;
el.draftToggle.addEventListener("change", () => {
  state.showDrafts = el.draftToggle.checked;
  localStorage.setItem("showDrafts", String(state.showDrafts));
  refresh();
});

function gold(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function heroImg(heroId) {
  const hero = state.heroes[String(heroId)];
  const img = document.createElement("img");
  img.src = hero ? hero.icon : "";
  img.alt = hero ? hero.name : `hero ${heroId}`;
  img.title = img.alt;
  img.loading = "lazy";
  // A missing portrait must not leave a broken-image glyph on the tile.
  img.addEventListener("error", () => img.remove());
  return img;
}

function draftRow(game) {
  const row = document.createElement("div");
  row.className = "draft";
  for (const side of ["radiant", "dire"]) {
    const box = document.createElement("div");
    box.className = `draft-side ${side}`;
    for (const heroId of game[side].picks) box.appendChild(heroImg(heroId));
    row.appendChild(box);
  }
  return row;
}

function networthRow(game) {
  const { side, amount } = game.net_worth_lead;
  const total = game.radiant.net_worth + game.dire.net_worth;
  // Cap the bar at a 25k swing so early-game noise doesn't peg it instantly.
  const fraction = total > 0 ? Math.min(amount / 25000, 1) : 0;

  const wrap = document.createElement("div");
  wrap.className = "networth";

  const bar = document.createElement("div");
  bar.className = "networth-bar";
  const fill = document.createElement("div");
  fill.className = `networth-fill ${side}`;
  fill.style[side === "radiant" ? "left" : "right"] = `${50 - fraction * 50}%`;
  bar.appendChild(fill);

  const label = document.createElement("div");
  label.className = "networth-label";
  if (amount === 0) {
    label.textContent = "even";
  } else {
    label.innerHTML = `<b class="${side}">${side === "radiant" ? game.radiant.name : game.dire.name}</b> +${gold(amount)}`;
  }

  wrap.append(bar, label);
  return wrap;
}

/* Which wall tile each game drives.
 *
 * Nothing in Valve's data identifies which Twitch/YouTube stream is showing a
 * given match, so this mapping cannot be derived - it has to be stated. Keyed
 * by match_id and remembered, defaulting to the game's position on screen,
 * which is right whenever streams.toml is ordered the same way.
 */
function wallTileFor(game, position) {
  const saved = JSON.parse(localStorage.getItem("wallMap") || "{}");
  const count = Math.max(state.wallCount || 4, 1);
  // Wrap: with league_id unset there can be more live games than wall tiles,
  // and a default of "position" would point at a stream that does not exist.
  return saved[game.match_id] ?? position % count;
}

function setWallTile(matchId, tile) {
  const saved = JSON.parse(localStorage.getItem("wallMap") || "{}");
  saved[matchId] = tile;
  localStorage.setItem("wallMap", JSON.stringify(saved));
}

async function switchWallAudio(tile, node) {
  if (!state.wallEnabled) return;
  node.classList.add("switching");
  try {
    const res = await fetch(`/api/wall/audio/${tile}`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
    state.activeWallTile = tile;
    document.querySelectorAll(".tile").forEach((t) =>
      t.classList.toggle("audio", Number(t.dataset.wallTile) === tile));
  } catch (err) {
    node.classList.add("failed");
    el.status.textContent = `wall: ${err.message}`;
    el.status.className = "status error";
    setTimeout(() => node.classList.remove("failed"), 2000);
  } finally {
    node.classList.remove("switching");
  }
}

function tile(game, position) {
  const node = document.createElement("article");
  node.className = "tile" + (game.in_progress ? "" : " pregame");

  const wallTile = wallTileFor(game, position);
  node.dataset.wallTile = wallTile;
  if (state.wallEnabled) {
    node.classList.add("clickable");
    if (wallTile === state.activeWallTile) node.classList.add("audio");
    node.title = `Click to move wall audio to stream ${wallTile + 1}`;
    node.addEventListener("click", () => switchWallAudio(wallTile, node));

    // The badge states the mapping and cycles it, so a wrong guess is one
    // click to fix rather than a config edit and a restart.
    const badge = document.createElement("button");
    badge.className = "wall-badge";
    badge.textContent = `▶ ${wallTile + 1}`;
    badge.title = "Which wall stream this game is on. Click to change.";
    badge.addEventListener("click", (event) => {
      event.stopPropagation();
      const next = (wallTile + 1) % Math.max(state.wallCount || 4, 1);
      setWallTile(game.match_id, next);
      refresh();
    });
    node.appendChild(badge);
  }

  const teams = document.createElement("div");
  teams.className = "teams";
  teams.innerHTML = `
    <div class="team-name radiant"></div>
    <div class="series">${game.series_score}</div>
    <div class="team-name dire"></div>`;
  // textContent, not innerHTML: team names are attacker-controllable strings.
  teams.querySelector(".team-name.radiant").textContent = game.radiant.name;
  teams.querySelector(".team-name.dire").textContent = game.dire.name;

  const score = document.createElement("div");
  score.className = "score";
  score.innerHTML = `
    <span class="radiant">${game.radiant.score}</span>
    <span class="clock">${game.clock}</span>
    <span class="dire">${game.dire.score}</span>`;

  node.append(teams, score, networthRow(game));
  if (state.showDrafts && game.radiant.picks.length) node.appendChild(draftRow(game));
  return node;
}

function renderStatus(data) {
  const parts = [];
  let level = "";

  if (data.warming_up) {
    parts.push(`warming up - less than ${Math.round(data.delay_seconds)}s of history`);
    level = "warn";
  }
  if (data.poll.stale) {
    const err = data.poll.last_error ? `: ${data.poll.last_error}` : "";
    parts.push(`STALE - Valve API not responding${err}`);
    level = "error";
  }
  if (!parts.length) {
    parts.push(`${data.games.length} live - showing ${Math.round(data.snapshot_age ?? 0)}s behind`);
  }

  /* league_id=0 means "every live league game anywhere", which is dozens of
     low-tier matches. Easy to mistake one for a TI game, so say it out loud. */
  if (!data.league_id) {
    parts.push("ALL leagues - set league_id in config.toml to show only TI");
    if (level !== "error") level = "warn";
  }

  el.status.textContent = parts.join("  |  ");
  el.status.className = `status ${level}`;
}

/* TI's group stage runs four concurrent games, so four must land as 2x2 rather
   than one wide row. Beyond four we go to three columns and let rows wrap. */
function columnsFor(count) {
  if (count <= 1) return 1;
  if (count <= 4) return 2;
  if (count <= 9) return 3;
  return 4;
}

/* Scale the type off the tile, not the viewport.
   Four games in a 2x2 gives tiles roughly four times the area of a nine-up
   grid, so a viewport-based size left the TI layout looking tiny with acres of
   empty tile around it. This makes the score as large as the tile can carry.
   The two factors are the fraction of tile width and height one "unit" takes;
   the smaller wins so text never overflows either axis. */
function sizeToTiles(count) {
  if (!count) return;
  const cols = columnsFor(count);
  const rows = Math.ceil(count / cols);
  const style = getComputedStyle(el.grid);
  const gap = parseFloat(style.gap) || 0;

  const tileW = (el.grid.clientWidth - gap * (cols - 1)) / cols;
  const tileH = (el.grid.clientHeight - gap * (rows - 1)) / rows;

  const unit = Math.max(12, Math.min(tileW * 0.052, tileH * 0.105, 52));
  el.grid.style.setProperty("--unit", `${unit.toFixed(1)}px`);
}

function render(data) {
  renderStatus(data);
  el.grid.style.setProperty("--cols", columnsFor(data.games.length));
  sizeToTiles(data.games.length);
  el.grid.replaceChildren();

  if (!data.games.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = data.league_id
      ? `No live games for league ${data.league_id}.`
      : "No live league games right now.";
    el.grid.appendChild(empty);
    return;
  }

  data.games.forEach((game, position) => el.grid.appendChild(tile(game, position)));
}

async function loadWallStatus() {
  try {
    const wall = await (await fetch("/api/wall")).json();
    state.wallEnabled = Boolean(wall.enabled) && !wall.error;
    state.wallCount = wall.count ?? 4;
    state.activeWallTile = wall.active ?? null;
  } catch {
    state.wallEnabled = false;
  }
}

async function refresh() {
  try {
    // Omitting the parameter entirely lets the server's configured default win.
    const query = state.delay === null ? "" : `?delay=${state.delay}`;
    const res = await fetch(`/api/games${query}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    if (state.delay === null) {
      /* Valve reports the actual broadcast delay per game, so prefer it over
         the configured guess. This is the difference between the delay being
         right from the first game and you discovering it by watching a kill
         get spoiled. */
      state.delay = clampDelay(data.suggested_delay ?? data.delay_seconds);
      state.delayFromValve = data.suggested_delay != null;
      renderDelay();
    }
    render(data);
  } catch (err) {
    el.status.textContent = `cannot reach scoreboard server: ${err.message}`;
    el.status.className = "status error";
  }
}

async function loadHeroes() {
  try {
    state.heroes = await (await fetch("/api/heroes")).json();
  } catch {
    // Drafts degrade to nothing; every other number on the tile still works.
  }
}

/* Wipes this browser's saved settings and reloads with the cache bypassed.
   Two distinct failure modes it clears:
     - a stale saved delay from an earlier session showing the wrong offset
     - assets held in memory after the page has been open for days
   The cache-busting query string is what makes it a *hard* refresh; a plain
   location.reload() can reuse the in-memory copies. */
el.hardRefresh.addEventListener("click", async () => {
  el.hardRefresh.textContent = "reloading...";
  localStorage.removeItem("delaySeconds");
  localStorage.removeItem("showDrafts");
  try {
    await fetch("/static/app.js", { cache: "reload" });
    await fetch("/static/style.css", { cache: "reload" });
  } catch {
    // Offline or server down; reload anyway so the error state is visible.
  }
  location.replace(`${location.pathname}?r=${Date.now()}`);
});

// Going fullscreen or moving the window between displays changes the tile size.
window.addEventListener("resize", () => {
  const tiles = el.grid.childElementCount;
  if (tiles) sizeToTiles(tiles);
});

renderDelay();
Promise.all([loadHeroes(), loadWallStatus()]).then(refresh);
setInterval(refresh, REFRESH_MS);
// The wall can be started after the scoreboard, so keep checking for it.
setInterval(loadWallStatus, 15000);
