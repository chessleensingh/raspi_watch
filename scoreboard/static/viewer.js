/* Viewer client - the main screen.
 *
 * Every configured stream is loaded at once and left playing, muted, stacked on
 * top of each other. Selecting one raises it and unmutes it. That is the whole
 * trick: switching costs nothing because the stream is already buffered, which
 * is the reason for paying four concurrent decodes.
 *
 * Players are driven through YouTube's and Twitch's JS APIs rather than plain
 * iframes because mute state has to be changed programmatically. A bare iframe
 * can only be unmuted by reloading it with different parameters, which would
 * re-buffer on every switch and defeat the point.
 */

const POLL_MS = 500;

const state = {
  streams: [],
  players: new Map(),   // index -> { mute(), unmute() }
  showing: null,
  /* Autoplay must start muted and only a gesture on THIS window may unmute.
     Until that happens the picture switches silently. */
  armed: false,
};

const el = {
  stack: document.getElementById("stack"),
  label: document.getElementById("label"),
  unmute: document.getElementById("unmute"),
  toast: document.getElementById("toast"),
};

function toast(message, isError = false) {
  el.toast.textContent = message;
  el.toast.className = `toast visible${isError ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.toast.className = "toast"), 3000);
}

function showLabel(text) {
  el.label.textContent = text;
  el.label.classList.add("visible");
  clearTimeout(showLabel.timer);
  showLabel.timer = setTimeout(() => el.label.classList.remove("visible"), 2500);
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = src;
    tag.onload = resolve;
    tag.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.appendChild(tag);
  });
}

/* The YouTube API signals readiness through one global callback, so the promise
   is created before the script tag and resolved from it. */
const youTubeReady = new Promise((resolve) => {
  window.onYouTubeIframeAPIReady = resolve;
});

function makeYouTubePlayer(container, stream) {
  const host = document.createElement("div");
  container.appendChild(host);

  const player = new YT.Player(host, {
    videoId: stream.id,
    playerVars: {
      autoplay: 1,
      mute: 1,
      controls: 0,
      modestbranding: 1,
      rel: 0,
      playsinline: 1,
      // The viewer has its own key handling; YouTube's would fight it.
      disablekb: 1,
    },
    events: {
      onReady: (event) => event.target.playVideo(),
      onError: () => toast(`stream ${stream.index + 1} failed to load`, true),
    },
  });

  return {
    mute: () => player.mute(),
    unmute: () => {
      player.unMute();
      player.setVolume(100);
    },
  };
}

function makeTwitchPlayer(container, stream) {
  const host = document.createElement("div");
  host.id = `twitch-${stream.index}`;
  container.appendChild(host);

  /* Twitch requires the embedding hostname up front. Taking it from the
     location means this works at localhost and at the LAN name without a
     config entry; it fails only under a name Twitch rejects. */
  const embed = new Twitch.Embed(host.id, {
    channel: stream.id,
    parent: [location.hostname],
    width: "100%",
    height: "100%",
    layout: "video",
    autoplay: true,
    muted: true,
  });

  let player = null;
  embed.addEventListener(Twitch.Embed.VIDEO_READY, () => {
    player = embed.getPlayer();
    player.setMuted(true);
  });

  return {
    mute: () => player && player.setMuted(true),
    unmute: () => {
      if (!player) return;
      player.setMuted(false);
      player.setVolume(1);
    },
  };
}

function makeEmptyPlayer(container, stream) {
  container.classList.add("empty");
  container.textContent = stream.label;
  // Nothing to mute, but the interface has to match so show() stays simple.
  return { mute: () => {}, unmute: () => {} };
}

async function buildPlayers(streams) {
  const kinds = new Set(streams.map((s) => s.kind));

  /* Only fetch the API a configured stream actually needs. A YouTube-only
     setup should not fail because Twitch's script is unreachable. */
  if (kinds.has("youtube")) {
    await loadScript("https://www.youtube.com/iframe_api");
    await youTubeReady;
  }
  if (kinds.has("twitch")) {
    await loadScript("https://embed.twitch.tv/embed/v1.js");
  }

  for (const stream of streams) {
    const container = document.createElement("div");
    container.className = "player";
    container.dataset.index = stream.index;
    el.stack.appendChild(container);

    let player;
    if (stream.kind === "youtube") player = makeYouTubePlayer(container, stream);
    else if (stream.kind === "twitch") player = makeTwitchPlayer(container, stream);
    else player = makeEmptyPlayer(container, stream);

    state.players.set(stream.index, player);
  }
}

function show(index) {
  if (index === state.showing) return;
  const stream = state.streams[index];
  if (!stream) return;

  document.querySelectorAll(".player").forEach((node) =>
    node.classList.toggle("showing", Number(node.dataset.index) === index));

  // Mute everything else first, so two streams never talk over each other.
  for (const [i, player] of state.players) {
    if (i !== index) player.mute();
  }
  if (state.armed) state.players.get(index)?.unmute();

  state.showing = index;
  showLabel(`${index + 1}  ${stream.label}`);
}

function arm() {
  if (state.armed) return;
  state.armed = true;
  el.unmute.hidden = true;
  if (state.showing !== null) state.players.get(state.showing)?.unmute();
  showLabel("sound on");
}

function toggleMute() {
  if (!state.armed) return arm();
  state.armed = false;
  state.players.get(state.showing)?.mute();
  el.unmute.hidden = false;
  showLabel("muted");
}

async function poll() {
  try {
    const data = await (await fetch("/api/viewer")).json();
    // Nothing clicked yet: show the first stream rather than a black screen.
    show(data.selected ?? 0);
  } catch {
    // The server restarting must not tear down four working players. Keep
    // showing what we have and pick the selection back up when it returns.
  }
}

el.unmute.addEventListener("click", arm);

document.addEventListener("keydown", (event) => {
  const key = event.key.toLowerCase();
  if (key >= "1" && key <= "9") show(Number(key) - 1);
  else if (key === "m") toggleMute();
  else if (key === "f") {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  }
});

/* The cursor is hidden so it cannot sit over the picture; bring it back while
   the mouse is actually moving. */
let cursorTimer;
document.addEventListener("mousemove", () => {
  document.body.classList.add("pointer");
  clearTimeout(cursorTimer);
  cursorTimer = setTimeout(() => document.body.classList.remove("pointer"), 2000);
});

async function start() {
  try {
    const data = await (await fetch("/api/viewer")).json();
    state.streams = data.streams;
  } catch (err) {
    toast(`cannot reach the scoreboard server: ${err.message}`, true);
    return;
  }

  if (!state.streams.length) {
    el.stack.innerHTML =
      '<div class="player empty showing">No streams configured.<br>' +
      "Run <code>python wall/find_streams.py</code> and paste the IDs into " +
      "<code>wall/streams.toml</code>.</div>";
    return;
  }

  try {
    await buildPlayers(state.streams);
  } catch (err) {
    toast(err.message, true);
    return;
  }

  show(0);
  // Only offer sound once there is something to hear.
  el.unmute.hidden = false;
  setInterval(poll, POLL_MS);
}

start();
