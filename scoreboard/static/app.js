/* Scoreboard client.
 *
 * The delay lives here, not on the server: it is sent with each request and
 * persisted to localStorage. That keeps the server stateless and lets the table
 * screen and a phone run different delays if the broadcasts differ.
 */

const REFRESH_MS = 3000;
const DELAY_STEP = 15;
const MAX_DELAY = 900;

const state = {
  delay: clampDelay(Number(localStorage.getItem("delaySeconds") ?? 120)),
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
  const m = Math.floor(state.delay / 60);
  const s = state.delay % 60;
  el.delayValue.textContent = m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}

/* "+15s" means "show me newer data", i.e. a SMALLER delay. Labelling these by
   what the viewer wants rather than by the underlying number avoids the
   inverted-control confusion. */
el.delayUp.addEventListener("click", () => setDelay(state.delay - DELAY_STEP));
el.delayDown.addEventListener("click", () => setDelay(state.delay + DELAY_STEP));

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

  el.status.textContent = parts.join("  |  ");
  el.status.className = `status ${level}`;
}

function render(data) {
  renderStatus(data);
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
    const res = await fetch(`/api/games?delay=${state.delay}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
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

renderDelay();
loadHeroes().then(refresh);
setInterval(refresh, REFRESH_MS);
