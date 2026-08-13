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
