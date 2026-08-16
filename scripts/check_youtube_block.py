"""Is YouTube still blocking this machine?

On 2026-08-15 the viewer showed "Sign in to confirm you're not a bot" over every
stream. Signing the browser profile in changed nothing, and neither did loading
fewer embeds -- because the block is on the IP, not the profile or the pattern.
The proof was yt-dlp getting the identical message from the command line with no
browser involved at all.

So the question "can we go back to YouTube yet?" has a one-command answer:

    python scripts/check_youtube_block.py

Blocks like this lift on their own, typically in hours. Until it does, Twitch is
the working path:

    python -c "import sys; sys.path.insert(0,'.'); from wall.find_streams import *; \\
               write_streams_toml(__import__('pathlib').Path('wall/streams.toml'), \\
               TWITCH_ENGLISH, ['']*4)"
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wall.find_streams import yt_dlp_command  # noqa: E402

# A permanently available video, deliberately not a live one: the first probe
# used a 24/7 stream and reported "inconclusive" the day that stream ended,
# which is a check that fails for reasons unrelated to the question it asks.
PROBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def main() -> int:
    print("Asking YouTube for video metadata (no browser involved)...\n")
    result = subprocess.run(
        [*yt_dlp_command(), "--dump-single-json", "--no-warnings", PROBE_URL],
        capture_output=True, text=True, timeout=120,
    )

    stderr = result.stderr or ""
    if "not a bot" in stderr or "Sign in to confirm" in stderr:
        print("STILL BLOCKED. YouTube is refusing this IP address.")
        print("\nNothing in this repo can work around that: it is not the browser")
        print("profile, not the sign-in, and not how many embeds are open.")
        print("Stay on Twitch, and re-run this later -- these lift on their own.")
        return 1

    if result.returncode != 0:
        print(f"Inconclusive: yt-dlp failed for another reason.\n\n{stderr.strip()[:400]}")
        return 2

    try:
        data = json.loads(result.stdout)
    except ValueError:
        print("Inconclusive: could not parse the response.")
        return 2

    print("CLEAR. YouTube is answering normally again.")
    print(f"  probe title: {(data.get('title') or '')[:60]}")
    print("\nSwitch back with:")
    print("    python wall/find_streams.py --write")
    print("    .\\scripts\\start_all.ps1 -Restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
