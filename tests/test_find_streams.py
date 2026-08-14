"""Tests for locating yt-dlp.

find_streams.py used to run only on the Mac, where yt-dlp comes from Homebrew
and is always on PATH. It now runs on Windows, where `pip install yt-dlp` puts
the executable in a Scripts directory that is often not on PATH at all.
"""

import sys

import pytest

from wall.find_streams import printable, yt_dlp_command


def test_an_executable_on_path_is_preferred(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: r"C:\py\Scripts\yt-dlp.exe")

    assert yt_dlp_command() == [r"C:\py\Scripts\yt-dlp.exe"]


def test_falls_back_to_the_importable_module_when_not_on_path(monkeypatch):
    """The pip install works even when its Scripts dir is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setitem(sys.modules, "yt_dlp", object())

    assert yt_dlp_command() == [sys.executable, "-m", "yt_dlp"]


def test_missing_entirely_exits_with_the_install_command(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    monkeypatch.delitem(sys.modules, "yt_dlp", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        yt_dlp_command()

    assert "pip install yt-dlp" in str(exit_info.value)


# ---- console encoding ---------------------------------------------------
# The Windows console is cp1252. Stream titles are not: TI titles carry em
# dashes and team tags, and printing one raw raises UnicodeEncodeError midway
# through the results -- which is exactly when it is least welcome.


def test_ascii_titles_are_untouched():
    assert printable("Team Spirit vs Falcons", encoding="cp1252") == "Team Spirit vs Falcons"


def test_a_title_the_console_cannot_encode_does_not_raise():
    title = "TI 2026 \u2014 Day 1 \U0001f3c6 \u4e2d\u6587"

    result = printable(title, encoding="cp1252")

    assert isinstance(result, str)
    result.encode("cp1252")  # the whole point: this must not raise


def test_utf8_consoles_keep_every_character():
    title = "TI 2026 \u2014 Day 1 \U0001f3c6"

    assert printable(title, encoding="utf-8") == title


# ---- writing streams.toml ----------------------------------------------
# Hand-editing this file broke it twice: a regex meant to replace the streams
# array stopped at the first "]" and spliced the previous day's titles into the
# middle of the new ones, leaving TOML that would not parse -- which surfaces as
# "no streams configured" on screen, pointing nowhere near the cause.

from wall.find_streams import english_streams, write_streams_toml  # noqa: E402


def toml_with_arrays(path):
    path.write_text(
        '# leading comment\n'
        'streams = [\n  "old1",\n  "old2",\n]\n\n'
        '# titles comment\n'
        'titles = [\n  "old title 1",\n  "old title 2",\n]\n\n'
        'ytdl_format = "keep me"\n', encoding="utf-8")
    return path


def test_replaces_both_arrays(tmp_path):
    path = toml_with_arrays(tmp_path / "streams.toml")

    write_streams_toml(path, ["u1", "u2"], ["t1", "t2"])

    text = path.read_text(encoding="utf-8")
    assert "old1" not in text and "old title 1" not in text
    assert '"u1"' in text and '"t1"' in text


def test_keeps_the_rest_of_the_file(tmp_path):
    """The file carries hard-won comments and the quality settings."""
    path = toml_with_arrays(tmp_path / "streams.toml")

    write_streams_toml(path, ["u1"], ["t1"])

    text = path.read_text(encoding="utf-8")
    assert "# leading comment" in text
    assert 'ytdl_format = "keep me"' in text


def test_the_result_parses(tmp_path):
    from scoreboard.streams import load_streams
    path = toml_with_arrays(tmp_path / "streams.toml")

    write_streams_toml(path, ["https://youtu.be/aaa"], ["[EN-A] X vs Y"])

    streams = load_streams(path)
    assert streams[0].id == "aaa"
    assert streams[0].title == "[EN-A] X vs Y"


def test_a_file_with_no_titles_array_gains_one(tmp_path):
    path = tmp_path / "streams.toml"
    path.write_text('streams = [\n  "old",\n]\n', encoding="utf-8")

    write_streams_toml(path, ["https://youtu.be/aaa"], ["[EN-A] X vs Y"])

    from scoreboard.streams import load_streams
    assert load_streams(path)[0].title == "[EN-A] X vs Y"


def test_quotes_in_a_title_cannot_break_the_file(tmp_path):
    """Broadcast titles are not ours to control."""
    from scoreboard.streams import load_streams
    path = toml_with_arrays(tmp_path / "streams.toml")

    write_streams_toml(path, ["https://youtu.be/aaa"], ['a "quoted" title'])

    assert load_streams(path) != [], "the file no longer parses"


def test_english_streams_are_picked_in_slot_order():
    live = [
        {"url": "u-end", "title": "[EN-D] D vs d"},
        {"url": "u-ru", "title": "[RU-A] R vs r"},
        {"url": "u-ena", "title": "[EN-A] A vs a"},
    ]

    urls, titles = english_streams(live)

    assert urls == ["u-ena", "", "", "u-end"]
    assert titles[0] == "[EN-A] A vs a"
    assert titles[3] == "[EN-D] D vs d"
