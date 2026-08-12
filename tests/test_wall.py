"""Tests for the wall's pure parts: tiling maths and command construction.

Spawning players needs a real display, so that half is verified by hand with
--dry-run and a live run on the Mac.
"""

import sys

import pytest

from wall.wall import (
    Display,
    Geometry,
    build_command,
    choose_display,
    is_youtube,
    mirroring_is_on,
    parse_displays,
    tile_geometry,
)

# Real output shape from the Mac: built-in Retina panel plus an external TV.
SYSTEM_PROFILER = """
Graphics/Displays:

    Intel UHD Graphics 630:

      Displays:
        Color LCD:
          Resolution: 2880 x 1800 Retina
          Main Display: Yes
        S2-TEK TV:
          Resolution: 1920 x 1080 (1080p FHD - Full High Definition)
          Rotation: Supported
"""


YT_WATCH = "https://www.youtube.com/watch?v=abc123"
YT_LIVE = "https://www.youtube.com/@dota2/live"


def yt_command(entry=YT_WATCH, index=0, ytdl_format="bestvideo+bestaudio"):
    return build_command(
        entry, "1080p60,best", tile_geometry(1920, 1080, index), index,
        mpv_bin="/usr/local/bin/mpv", streamlink_bin="/usr/local/bin/streamlink",
        ytdl_format=ytdl_format,
    )


@pytest.mark.parametrize("entry,expected", [
    (YT_WATCH, True),
    (YT_LIVE, True),
    ("https://youtu.be/abc123", True),
    ("dota2ti", False),
    ("https://twitch.tv/dota2ti", False),
])
def test_youtube_entries_are_recognised(entry, expected):
    assert is_youtube(entry) is expected


def test_youtube_goes_straight_to_mpv_with_no_streamlink():
    cmd = yt_command()

    assert cmd[0] == "/usr/local/bin/mpv"
    assert cmd[1] == YT_WATCH
    assert "streamlink" not in " ".join(cmd)


def test_youtube_passes_the_quality_cap_to_ytdl():
    cmd = yt_command(ytdl_format="bestvideo[height<=?1080]+bestaudio")

    assert "--ytdl-format=bestvideo[height<=?1080]+bestaudio" in cmd


def test_youtube_tile_is_muted_and_placed_like_any_other():
    cmd = yt_command(index=3)

    assert "--mute=yes" in cmd
    assert "--geometry=960x540+960+540" in cmd
    assert "--input-ipc-server=/tmp/ti_wall_3.sock" in cmd


def test_youtube_and_twitch_tiles_can_coexist_on_distinct_sockets():
    """Nothing stops a mixed wall, and the sockets must still not collide."""
    yt = yt_command(index=0)
    twitch = build_command(
        "dota2ti", "best", tile_geometry(1920, 1080, 1), 1, "mpv", "streamlink",
    )

    yt_socket = next(a for a in yt if a.startswith("--input-ipc-server="))
    twitch_args = twitch[twitch.index("--player-args") + 1]

    assert yt_socket == "--input-ipc-server=/tmp/ti_wall_0.sock"
    assert "--input-ipc-server=/tmp/ti_wall_1.sock" in twitch_args


def test_full_twitch_url_is_not_double_prefixed():
    cmd = build_command(
        "https://twitch.tv/dota2ti", "best", tile_geometry(1920, 1080, 0), 0,
        "mpv", "streamlink",
    )

    assert "https://twitch.tv/dota2ti" in cmd
    assert "twitch.tv/https://twitch.tv/dota2ti" not in " ".join(cmd)


def test_four_tiles_form_a_2x2_covering_the_screen():
    tiles = [tile_geometry(1920, 1080, i, count=4) for i in range(4)]

    assert tiles[0] == Geometry(960, 540, 0, 0)
    assert tiles[1] == Geometry(960, 540, 960, 0)
    assert tiles[2] == Geometry(960, 540, 0, 540)
    assert tiles[3] == Geometry(960, 540, 960, 540)


def test_tiles_do_not_overlap_and_cover_the_full_area():
    screen_w, screen_h = 3840, 2160
    tiles = [tile_geometry(screen_w, screen_h, i, count=4) for i in range(4)]

    assert sum(t.width * t.height for t in tiles) == screen_w * screen_h
    corners = {(t.x, t.y) for t in tiles}
    assert len(corners) == 4


def test_odd_resolutions_do_not_produce_fractional_geometry():
    tiles = [tile_geometry(1367, 769, i, count=4) for i in range(4)]

    for tile in tiles:
        assert isinstance(tile.width, int) and isinstance(tile.height, int)
        assert tile.width > 0 and tile.height > 0


def test_single_stream_fills_the_screen():
    assert tile_geometry(1920, 1080, 0, count=1) == Geometry(1920, 1080, 0, 0)


def test_three_streams_still_tile_sensibly():
    """Streams go offline mid-tournament; three tiles must not break the layout."""
    tiles = [tile_geometry(1920, 1080, i, count=3) for i in range(3)]

    assert all(t.width == 960 and t.height == 540 for t in tiles)
    assert (tiles[2].x, tiles[2].y) == (0, 540)


def test_out_of_range_tile_index_is_rejected():
    with pytest.raises(ValueError):
        tile_geometry(1920, 1080, 4, count=4)
    with pytest.raises(ValueError):
        tile_geometry(1920, 1080, -1, count=4)


def test_geometry_renders_in_mpv_syntax():
    assert Geometry(960, 540, 960, 540).as_mpv_arg() == "960x540+960+540"


def test_command_targets_the_right_channel_and_socket():
    cmd = build_command(
        "dota2ti", "1080p60,best", tile_geometry(1920, 1080, 1), index=1,
        mpv_bin="/usr/local/bin/mpv", streamlink_bin="/usr/local/bin/streamlink",
    )

    assert cmd[0] == "/usr/local/bin/streamlink"
    assert "twitch.tv/dota2ti" in cmd
    assert "1080p60,best" in cmd

    player_args = cmd[cmd.index("--player-args") + 1]
    assert "--input-ipc-server=/tmp/ti_wall_1.sock" in player_args
    assert "--geometry=960x540+960+0" in player_args


def test_every_tile_starts_muted():
    """Four unmuted streams at once is unusable; audio is opt-in via hotkey."""
    for index in range(4):
        cmd = build_command(
            "chan", "best", tile_geometry(1920, 1080, index), index,
            mpv_bin="mpv", streamlink_bin="streamlink",
        )
        assert "--mute=yes" in cmd[cmd.index("--player-args") + 1]


def test_each_tile_gets_a_distinct_ipc_socket():
    sockets = set()
    for index in range(4):
        cmd = build_command(
            "chan", "best", tile_geometry(1920, 1080, index), index,
            mpv_bin="mpv", streamlink_bin="streamlink",
        )
        args = cmd[cmd.index("--player-args") + 1]
        sockets.add(next(a for a in args.split() if a.startswith("--input-ipc-server=")))

    assert len(sockets) == 4, "tiles would fight over one socket"


def test_hardware_decode_is_requested():
    cmd = build_command("chan", "best", tile_geometry(1920, 1080, 0), 0, "mpv", "streamlink")
    assert "--hwdec=videotoolbox" in cmd[cmd.index("--player-args") + 1]


def test_parse_displays_reads_names_sizes_and_retina_flag():
    displays = parse_displays(SYSTEM_PROFILER)

    assert len(displays) == 2
    assert displays[0] == Display("Color LCD", 2880, 1800, retina=True)
    assert displays[1] == Display("S2-TEK TV", 1920, 1080, retina=False)


def test_retina_reports_logical_points_not_physical_pixels():
    """Using the physical 2880x1800 would push three tiles off-screen."""
    assert Display("Color LCD", 2880, 1800, retina=True).logical_size == (1440, 900)
    assert Display("TV", 1920, 1080, retina=False).logical_size == (1920, 1080)


def test_external_display_wins_over_the_builtin_panel():
    """The TV is smaller than the laptop's Retina panel, but it is the point."""
    index, display = choose_display(parse_displays(SYSTEM_PROFILER))

    assert display.name == "S2-TEK TV"
    assert index == 1


def test_falls_back_to_the_builtin_when_nothing_else_is_attached():
    only_builtin = parse_displays("""
        Displays:
          Color LCD:
            Resolution: 2880 x 1800 Retina
    """)

    index, display = choose_display(only_builtin)
    assert (index, display.name) == (0, "Color LCD")


def test_choose_display_handles_no_displays():
    assert choose_display([]) is None
    assert parse_displays("no displays here") == []


def test_tiles_are_pinned_to_the_chosen_screen():
    """Without --screen every tile opens on the laptop panel, not the TV."""
    cmd = build_command(
        "dota2ti", "best", tile_geometry(1920, 1080, 0), 0, "mpv", "streamlink",
        screen_index=1,
    )
    args = cmd[cmd.index("--player-args") + 1]

    assert "--screen=1" in args
    assert "--fs-screen=1" in args


def test_youtube_tiles_also_respect_the_chosen_screen():
    cmd = yt_command(index=2)
    assert "--screen=0" in cmd

    cmd = build_command(
        YT_WATCH, "best", tile_geometry(1920, 1080, 2), 2, "mpv", "streamlink",
        ytdl_format="best", screen_index=1,
    )
    assert "--screen=1" in cmd


# ---------------------------------------------------------------------------
# The interactive key loop
#
# These were the gap that let a NameError sit in main() while all 64 other
# tests passed: nothing exercised the loop, so the crash only showed up by
# pressing a key on the TV.
# ---------------------------------------------------------------------------

def run_key_loop(monkeypatch, keys, streams=("a", "b", "c", "d")):
    """Drive main()'s loop over `keys`, spawning nothing. Returns tiles unmuted."""
    from wall import wall as W

    audio = []
    monkeypatch.setattr(W, "load_config", lambda *a, **k: W.WallConfig(
        streams=list(streams), quality="best", ytdl_format="",
        screen=(1920, 1080), screen_index=1,
    ))
    monkeypatch.setattr(W.Wall, "start_all", lambda self: None)
    monkeypatch.setattr(W.Wall, "stop_all", lambda self: None)
    monkeypatch.setattr(W.Wall, "respawn_dead", lambda self: None)
    monkeypatch.setattr(W.Wall, "set_audio", lambda self, i: audio.append(i))
    monkeypatch.setattr(W, "read_key", lambda: next(pending, "q"))
    monkeypatch.setattr(W.sys, "argv", ["wall.py"])
    # main() refuses to start if mpv/streamlink are missing. They are absent on
    # the Windows dev box, so point the lookup at an executable that exists
    # everywhere - otherwise these tests only pass on the Mac.
    monkeypatch.setattr(W.shutil, "which", lambda name: sys.executable)

    pending = iter(keys)
    assert W.main() == 0
    return audio


def test_number_keys_move_the_audio(monkeypatch):
    assert run_key_loop(monkeypatch, ["1", "3", "q"]) == [0, 2]


def test_poll_timeout_is_not_treated_as_a_keypress(monkeypatch):
    """read_key() returns "" on timeout, and "" is a substring of every string."""
    assert run_key_loop(monkeypatch, ["", "", "q"]) == []


def test_keys_beyond_the_configured_tiles_are_ignored(monkeypatch):
    assert run_key_loop(monkeypatch, ["1", "3", "q"], streams=("a", "b")) == [0]


# ---------------------------------------------------------------------------
# Live edge, not the DVR buffer
#
# `live-from-start` hands mpv an EDL of DVR segments it cannot open, so every
# YouTube tile died ~4s in and respawned forever. Found in the dress rehearsal
# on 2026-08-11; the flag had no test, so nothing caught it.
# ---------------------------------------------------------------------------

def test_youtube_tiles_start_at_the_live_edge():
    cmd = yt_command()
    raw = [a for a in cmd if a.startswith("--ytdl-raw-options=")]

    assert raw == ["--ytdl-raw-options=no-live-from-start="]


def test_the_dvr_buffer_option_is_never_passed():
    """The bare form is the one that kills the tile - it must not come back."""
    assert "--ytdl-raw-options=live-from-start=" not in yt_command()


# ---------------------------------------------------------------------------
# Display mirroring
# ---------------------------------------------------------------------------

MIRRORED_PROFILER = """
Graphics/Displays:

    Radeon Pro 560X:

      Displays:
        Color LCD:
          Resolution: 2880 x 1800 Retina
          Mirror: On
          Mirror Status: Hardware Mirror
        S2-TEK TV:
          Resolution: 1920 x 1080 (1080p FHD - Full High Definition)
          Main Display: Yes
          Mirror: On
          Mirror Status: Master Mirror
"""


def test_mirroring_is_read_off_the_profiler():
    assert mirroring_is_on(parse_displays(MIRRORED_PROFILER))


def test_extended_displays_are_not_reported_as_mirrored():
    assert not mirroring_is_on(parse_displays(SYSTEM_PROFILER))


def test_mirror_flag_does_not_disturb_the_parsed_geometry():
    """The Mirror lines sit between blocks; they must not shift names or sizes."""
    displays = parse_displays(MIRRORED_PROFILER)

    assert [d.name for d in displays] == ["Color LCD", "S2-TEK TV"]
    assert displays[0].logical_size == (1440, 900)
    assert displays[1].logical_size == (1920, 1080)


def test_mirrored_setup_falls_back_to_the_only_real_screen(monkeypatch):
    """mpv indexes real screens: mirrored means screen 1 does not exist."""
    from wall import wall as W

    monkeypatch.setattr(W.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": MIRRORED_PROFILER})())
    index, size, note = W.detect_display()

    assert index == 0
    assert size == (1920, 1080)
    assert "mirroring is ON" in note
