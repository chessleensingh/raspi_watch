/* Viewer client - the main screen.
 *
 * Every configured stream is loaded at once and left playing, muted, stacked on
 * top of each other. Selecting one raises it and unmutes it. That is the whole
 * trick: switching costs nothing because the stream is already buffered, which
 * is the reason for paying four concurrent decodes.
 *
 * Mute state has to change programmatically -- reloading an iframe to unmute it
 * would re-buffer on every switch and defeat the point -- so the players are
 * driven over postMessage with enablejsapi=1, which needs no third-party script.
 * See makeYouTubePlayer for why the script version was abandoned.
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

/* Which stream is showing, permanently in the corner.
 *
 * It used to fade after a couple of seconds, which was wrong: two Dota streams
 * look nearly identical, so without a label on screen there is no way to tell a
 * switch that worked from one that did nothing. Dim enough to ignore, present
 * enough to answer the question. */
function setLabel(text) {
  el.label.textContent = text;
  el.label.classList.add("visible");
}

/* Briefly brighten it, so a change catches the eye. */
function flashLabel() {
  el.label.classList.add("flash");
  clearTimeout(flashLabel.timer);
  flashLabel.timer = setTimeout(() => el.label.classList.remove("flash"), 1200);
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

/* A plain iframe driven by postMessage, NOT YouTube's iframe_api script.
 *
 * The script version is the documented path and was the first implementation,
 * but it puts a third-party script between the page and every player: Brave
 * Shields blocks https://www.youtube.com/iframe_api, buildPlayers() then never
 * resolves, and the viewer silently never starts polling -- no video, no
 * switching, no error that points at the cause.
 *
 * enablejsapi=1 exposes the same commands over postMessage, which needs no
 * script at all. Fewer moving parts, and nothing left for an ad blocker to
 * remove.
 */
function makeYouTubePlayer(container, stream) {
  const params = new URLSearchParams({
    autoplay: "1",
    mute: "1",
    controls: "0",
    modestbranding: "1",
    rel: "0",
    playsinline: "1",
    enablejsapi: "1",
    // The viewer has its own key handling; YouTube's would fight it.
    disablekb: "1",
    origin: location.origin,
  });

  const frame = document.createElement("iframe");
  frame.src = `https://www.youtube.com/embed/${stream.id}?${params}`;
  // Without this the browser refuses the autoplay even though it is muted.
  frame.allow = "autoplay; encrypted-media; picture-in-picture";
  frame.setAttribute("frameborder", "0");
  container.appendChild(frame);

  const command = (func, args = []) => {
    try {
      frame.contentWindow?.postMessage(
        JSON.stringify({ event: "command", func, args }), "*");
    } catch {
      // A player that refuses to change volume must not stop the switch.
    }
  };

  return {
    mute: () => command("mute"),
    unmute: () => {
      command("unMute");
      command("setVolume", [100]);
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

  /* YouTube needs no script at all -- see makeYouTubePlayer. Twitch still does,
     and it is the fallback path, so a failure to load it must not take the
     whole page down when the configured streams are all YouTube. */
  if (kinds.has("twitch")) {
    try {
      await loadScript("https://embed.twitch.tv/embed/v1.js");
    } catch (err) {
      toast("Twitch embeds unavailable; those slots will stay blank", true);
    }
  }

  for (const stream of streams) {
    const container = document.createElement("div");
    container.className = "player";
    container.dataset.index = stream.index;
    el.stack.appendChild(container);

    /* One player that refuses to build must not cost you the other three, nor
       stop the page from starting its poll loop. That failure mode -- an
       exception here leaving the viewer alive but deaf to the scoreboard -- is
       worse than a blank slot, because nothing on screen explains it. */
    let player;
    try {
      if (stream.kind === "youtube") player = makeYouTubePlayer(container, stream);
      else if (stream.kind === "twitch") player = makeTwitchPlayer(container, stream);
      else player = makeEmptyPlayer(container, stream);
    } catch (err) {
      container.classList.add("empty");
      container.textContent = `stream ${stream.index + 1} failed to load`;
      player = { mute: () => {}, unmute: () => {} };
      toast(`stream ${stream.index + 1}: ${err.message}`, true);
    }

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
  // The bare video id is noise; the number is what you press and what the
  // scoreboard badge shows.
  setLabel(`STREAM ${index + 1}${state.armed ? "" : "  (muted)"}`);
  flashLabel();
}

function arm() {
  if (state.armed) return;
  state.armed = true;
  el.unmute.hidden = true;
  if (state.showing !== null) state.players.get(state.showing)?.unmute();
  setLabel(`STREAM ${state.showing + 1}`);
  flashLabel();
}

function toggleMute() {
  if (!state.armed) return arm();
  state.armed = false;
  state.players.get(state.showing)?.mute();
  el.unmute.hidden = false;
  setLabel(`STREAM ${state.showing + 1}  (muted)`);
  flashLabel();
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

/* Pressing a number here must tell the SERVER, not just this page.
 *
 * show() alone lasts 500ms: the next poll reads the server's selection, sees the
 * old value, and puts it straight back -- so the key looked like it did nothing
 * but flicker. Posting it makes this page and the scoreboard agree on one
 * answer, and keeps the scoreboard's highlight in step with keys pressed here.
 *
 * show() still runs first so the switch is instant rather than waiting on the
 * round trip; the poll confirms it a moment later. */
async function select(index) {
  if (!state.streams[index]) return;
  show(index);
  try {
    await fetch(`/api/viewer/select/${index}`, { method: "POST" });
  } catch {
    // Server down: the local switch stands, and polling reconciles on return.
  }
}

document.addEventListener("keydown", (event) => {
  const key = event.key.toLowerCase();
  if (key >= "1" && key <= "9") select(Number(key) - 1);
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
