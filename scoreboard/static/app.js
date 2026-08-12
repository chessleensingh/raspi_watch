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
  showDrafts: localStorage.getItem("showDrafts") === "true",
  heroes: {},
};

const el = {
  grid: document.getElementById("grid"),
  status: document.getElementById("status"),
  delayValue: document.getElementById("delay-value"),
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

function tile(game) {
  const node = document.createElement("article");
  node.className = "tile" + (game.in_progress ? "" : " pregame");

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

function render(data) {
  renderStatus(data);
  el.grid.style.setProperty("--cols", columnsFor(data.games.length));
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

  for (const game of data.games) el.grid.appendChild(tile(game));
}

async function refresh() {
  try {
    // Omitting the parameter entirely lets the server's configured default win.
    const query = state.delay === null ? "" : `?delay=${state.delay}`;
    const res = await fetch(`/api/games${query}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    if (state.delay === null) {
      state.delay = clampDelay(data.delay_seconds);
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

renderDelay();
loadHeroes().then(refresh);
setInterval(refresh, REFRESH_MS);
