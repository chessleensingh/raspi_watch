"""Tests for resolving streams.toml entries into browser-embeddable descriptors.

The viewer runs in a browser, so it needs concrete video IDs and channel names --
not the mpv/streamlink targets wall.py consumes from the same file.
"""

import pytest

from scoreboard.streams import Stream, load_streams


def write_streams(tmp_path, entries):
    body = "streams = [\n" + "".join(f'  "{e}",\n' for e in entries) + "]\n"
    path = tmp_path / "streams.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_youtube_watch_url_resolves_to_its_video_id(tmp_path):
    path = write_streams(tmp_path, ["https://www.youtube.com/watch?v=abc123XYZ_-"])

    streams = load_streams(path)

    assert streams == [
        Stream(index=0, kind="youtube", id="abc123XYZ_-",
               label="https://www.youtube.com/watch?v=abc123XYZ_-")
    ]


def test_youtube_watch_url_with_extra_parameters_still_resolves(tmp_path):
    """find_streams.py output and copy-pasted links carry &t=, &list= and friends."""
    path = write_streams(tmp_path, ["https://www.youtube.com/watch?v=abc123&t=90s"])

    assert load_streams(path)[0].id == "abc123"


def test_short_youtu_be_url_resolves_to_its_video_id(tmp_path):
    path = write_streams(tmp_path, ["https://youtu.be/abc123"])

    assert load_streams(path)[0] == Stream(
        index=0, kind="youtube", id="abc123", label="https://youtu.be/abc123"
    )


def test_channel_live_url_is_empty_because_it_cannot_be_embedded(tmp_path):
    """YouTube embeds need a concrete video ID; @channel/live has none.

    This is the form streams.toml ships with, so it must degrade to a labelled
    empty slot rather than a broken player.
    """
    path = write_streams(tmp_path, ["https://www.youtube.com/@dota2/live"])

    stream = load_streams(path)[0]
    assert stream.kind == "empty"
    assert "@dota2/live" in stream.label


def test_bare_name_is_a_twitch_channel(tmp_path):
    path = write_streams(tmp_path, ["dota2ti_2"])

    assert load_streams(path)[0] == Stream(
        index=0, kind="twitch", id="dota2ti_2", label="twitch.tv/dota2ti_2"
    )


def test_blank_entry_is_an_empty_slot(tmp_path):
    path = write_streams(tmp_path, [""])

    assert load_streams(path)[0].kind == "empty"


def test_indexes_follow_file_order(tmp_path):
    path = write_streams(tmp_path, ["https://youtu.be/a", "", "dota2ti", "https://youtu.be/d"])

    streams = load_streams(path)

    assert [s.index for s in streams] == [0, 1, 2, 3]
    assert [s.kind for s in streams] == ["youtube", "empty", "twitch", "youtube"]


def test_missing_file_yields_no_streams_rather_than_raising(tmp_path):
    """A missing stream config must never stop the scoreboard from starting."""
    assert load_streams(tmp_path / "nope.toml") == []


def test_malformed_toml_yields_no_streams_rather_than_raising(tmp_path):
    path = tmp_path / "streams.toml"
    path.write_text('streams = [ "unterminated', encoding="utf-8")

    assert load_streams(path) == []


def test_file_without_a_streams_key_yields_no_streams(tmp_path):
    path = tmp_path / "streams.toml"
    path.write_text('quality = "best"\n', encoding="utf-8")

    assert load_streams(path) == []


def test_byte_order_mark_does_not_break_parsing(tmp_path):
    """Editors on Windows write a BOM and tomllib rejects it outright."""
    path = tmp_path / "streams.toml"
    path.write_text('streams = [ "https://youtu.be/abc" ]\n', encoding="utf-8-sig")

    assert load_streams(path)[0].id == "abc"


def test_to_dict_is_json_ready_for_the_viewer(tmp_path):
    path = write_streams(tmp_path, ["https://youtu.be/abc"])

    assert load_streams(path)[0].to_dict() == {
        "index": 0, "kind": "youtube", "id": "abc",
        "label": "https://youtu.be/abc", "title": "",
    }


# ---- titles -------------------------------------------------------------
# Valve's game payload has no field naming the stream, but the STREAM's title
# names the teams: "[EN-A] Team Falcons vs. LGD Gaming - The International...".
# Carrying that through is what lets a game be matched to its stream instead of
# guessed from screen position.


def test_titles_are_paired_with_streams_by_position(tmp_path):
    path = tmp_path / "streams.toml"
    path.write_text(
        'streams = [ "https://youtu.be/aaa", "https://youtu.be/bbb" ]\n'
        'titles = [ "[EN-A] Team Falcons vs. LGD Gaming", "[EN-B] Nigma vs Iron Wing" ]\n',
        encoding="utf-8")

    streams = load_streams(path)

    assert streams[0].title == "[EN-A] Team Falcons vs. LGD Gaming"
    assert streams[1].title == "[EN-B] Nigma vs Iron Wing"


def test_a_missing_titles_list_is_not_an_error(tmp_path):
    """streams.toml files written before titles existed must still load."""
    path = write_streams(tmp_path, ["https://youtu.be/aaa"])

    assert load_streams(path)[0].title == ""


def test_fewer_titles_than_streams_leaves_the_rest_blank(tmp_path):
    path = tmp_path / "streams.toml"
    path.write_text(
        'streams = [ "https://youtu.be/aaa", "https://youtu.be/bbb" ]\n'
        'titles = [ "only the first" ]\n', encoding="utf-8")

    streams = load_streams(path)

    assert streams[0].title == "only the first"
    assert streams[1].title == ""


def test_title_is_exposed_to_the_client(tmp_path):
    path = tmp_path / "streams.toml"
    path.write_text('streams = [ "https://youtu.be/aaa" ]\ntitles = [ "[EN-A] X vs Y" ]\n',
                    encoding="utf-8")

    assert load_streams(path)[0].to_dict()["title"] == "[EN-A] X vs Y"
