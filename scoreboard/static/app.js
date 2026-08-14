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
  viewerEnabled: false,
  streamCount: 4,
  activeStream: null,
  streams: [],
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

function heroImg(heroId, carrying = false) {
  const hero = state.heroes[String(heroId)];
  const img = document.createElement("img");
  img.src = hero ? hero.icon : "";
  img.alt = hero ? hero.name : `hero ${heroId}`;
  img.title = img.alt;
  img.loading = "lazy";
  if (carrying) {
    img.classList.add("rapier");
    img.title = `${img.alt} - DIVINE RAPIER`;
  }
  // A missing portrait must not leave a broken-image glyph on the tile.
  img.addEventListener("error", () => img.remove());
  return img;
}

/* One team's picks, stacked vertically to sit under that team's name.
   Kept as a column rather than a row because a row of ten 16:9 portraits cannot
   fit a tile's width at a readable size -- see the .draft rules. */
function draftColumn(game, side) {
  const box = document.createElement("div");
  box.className = `draft-side ${side}`;
  const carriers = game[side].rapier_heroes || [];
  for (const heroId of game[side].picks) {
    box.appendChild(heroImg(heroId, carriers.includes(heroId)));
  }
  return box;
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

/* Which stream each game is on.
 *
 * Nothing in Valve's data identifies which Twitch/YouTube stream is showing a
 * given match, so this mapping cannot be derived - it has to be stated. Keyed
 * by match_id and remembered, defaulting to the game's position on screen,
 * which is right whenever streams.toml is ordered the same way.
 */
/* Normalize a team name for comparison against a stream title. Broadcast
   titles punctuate differently to Valve's team names -- "LGD Gaming" against
   "PSG.LGD", "Nigma Galaxy " with a trailing space -- so compare on letters
   and digits only. */
function nameKey(name) {
  return (name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

/* Which stream a game is on, by matching team names against the stream title.
   "[EN-A] Team Falcons vs. LGD Gaming - The International 2026" names both
   teams, so a game whose two names both appear in one title is on that stream.
   Requiring BOTH avoids matching the wrong game of a team playing twice. */
function matchStreamByTitle(game) {
  const radiant = nameKey(game.radiant.name);
  const dire = nameKey(game.dire.name);
  if (!radiant || !dire) return null;

  for (const stream of state.streams) {
    const title = nameKey(stream.title);
    if (!title) continue;
    if (title.includes(radiant) && title.includes(dire)) return stream.index;
  }
  return null;
}

function streamFor(game, position) {
  /* An explicit choice always wins: the badge exists precisely for when the
     automatic answer is wrong, and it must not be silently overridden. */
  const saved = JSON.parse(localStorage.getItem("streamMap") || "{}");
  if (saved[game.match_id] !== undefined) return saved[game.match_id];

  const matched = matchStreamByTitle(game);
  if (matched !== null) return matched;

  const count = Math.max(state.streamCount || 4, 1);
  // Wrap: with league_id unset there can be more live games than streams, and
  // a default of "position" would point at one that does not exist.
  return position % count;
}

function setStreamFor(matchId, index) {
  const saved = JSON.parse(localStorage.getItem("streamMap") || "{}");
  saved[matchId] = index;
  localStorage.setItem("streamMap", JSON.stringify(saved));
}

async function selectStream(index, node) {
  if (!state.viewerEnabled) return;
  node.classList.add("switching");
  try {
    const res = await fetch(`/api/viewer/select/${index}`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
    state.activeStream = index;
    document.querySelectorAll(".tile").forEach((t) =>
      t.classList.toggle("audio", Number(t.dataset.stream) === index));
  } catch (err) {
    node.classList.add("failed");
    el.status.textContent = `viewer: ${err.message}`;
    el.status.className = "status error";
    setTimeout(() => node.classList.remove("failed"), 2000);
  } finally {
    node.classList.remove("switching");
  }
}

/* The tile border is the LAST resort for a Rapier, not the first.
   The marks belong on the thing they describe -- the carrier's portrait, the
   holding team's name -- but the portraits only exist while Drafts is on, so
   with drafts hidden a Rapier would otherwise go unannounced entirely. */
function alertClass(game) {
  if (state.showDrafts) return "";
  return (game.radiant.has_rapier || game.dire.has_rapier) ? " rapier" : "";
}

function tile(game, position) {
  const node = document.createElement("article");
  node.className = "tile" + (game.in_progress ? "" : " pregame") + alertClass(game);

  const stream = streamFor(game, position);
  node.dataset.stream = stream;
  if (state.viewerEnabled) {
    node.classList.add("clickable");
    if (stream === state.activeStream) node.classList.add("audio");
    node.title = `Click to put stream ${stream + 1} on the main screen`;
    node.addEventListener("click", () => selectStream(stream, node));

    // The badge states the mapping and cycles it, so a wrong guess is one
    // click to fix rather than a config edit and a restart.
    const badge = document.createElement("button");
    badge.className = "stream-badge";
    badge.textContent = `▶ ${stream + 1}`;
    badge.title = "Which stream this game is on. Click to change.";
    badge.addEventListener("click", (event) => {
      event.stopPropagation();
      const next = (stream + 1) % Math.max(state.streamCount || 4, 1);
      setStreamFor(game.match_id, next);
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
  for (const side of ["radiant", "dire"]) {
    const el = teams.querySelector(`.team-name.${side}`);
    el.textContent = game[side].name;
    if (game[side].has_aegis) {
      el.classList.add("aegis");
      el.title = `${game[side].name} holds the Aegis`;
    }
  }

  const score = document.createElement("div");
  score.className = "score";
  score.innerHTML = `
    <span class="radiant">${game.radiant.score}</span>
    <span class="clock">${game.clock}</span>
    <span class="dire">${game.dire.score}</span>`;

  /* Picks flank the score rather than sitting under everything, so each team's
     heroes line up beneath that team's name and the score keeps the middle. */
  const body = document.createElement("div");
  body.className = "body";

  const middle = document.createElement("div");
  middle.className = "middle";
  middle.append(score, networthRow(game));

  const drafting = state.showDrafts && game.radiant.picks.length;
  if (drafting) body.appendChild(draftColumn(game, "radiant"));
  body.appendChild(middle);
  if (drafting) body.appendChild(draftColumn(game, "dire"));

  node.append(teams, body);
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
    /* Distinguish "you set the wrong id" from "Valve is not publishing", which
       look identical on screen and lead to opposite actions. During TI 2026's
       first round the feed carried TI matches only around the draft and dropped
       them once play started, so an empty board with a correct id is expected
       rather than a fault to go hunting for. */
    empty.textContent = data.league_id
      ? `Nothing in Valve's feed for league ${data.league_id} right now. `
        + `Matches can drop out of the feed mid-game; this fills in by itself `
        + `when they come back.`
      : "No live league games right now.";
    el.grid.appendChild(empty);
    return;
  }

  data.games.forEach((game, position) => el.grid.appendChild(tile(game, position)));
}

async function loadViewerStatus() {
  try {
    const viewer = await (await fetch("/api/viewer")).json();
    // No streams configured means clicking a game could do nothing useful, so
    // the tiles stay unclickable rather than failing on every press.
    state.viewerEnabled = (viewer.count ?? 0) > 0;
    state.streamCount = viewer.count ?? 4;
    state.streams = viewer.streams ?? [];
    state.activeStream = viewer.selected ?? null;
  } catch {
    state.viewerEnabled = false;
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
  /* Also the game-to-stream overrides. A choice made by hand outranks the
     title matching, correctly -- but that means a badge cycled before the
     matching existed keeps winning forever, and there would otherwise be no
     way to hand control back. */
  localStorage.removeItem("streamMap");
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
Promise.all([loadHeroes(), loadViewerStatus()]).then(refresh);
setInterval(refresh, REFRESH_MS);
// The viewer's selection can change from its own keyboard, so keep the
// highlight on the scoreboard in step with it.
setInterval(loadViewerStatus, 15000);
