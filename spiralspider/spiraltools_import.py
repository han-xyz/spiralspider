"""The spiraltools package of the sibling spiraldb repo: its wiki page parser, cache layout and world registry."""
import os
import sys

SPIRALTOOLS = os.environ.get("SPIRALTOOLS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spiraldb", "tools")

if os.path.isdir(os.path.join(SPIRALTOOLS, "spiraltools")) and SPIRALTOOLS not in sys.path:
    sys.path.append(SPIRALTOOLS)

try:
    from spiraltools.quests import archive
    from spiraltools.worlds import WORLDS, world
except ModuleNotFoundError as e:
    raise SystemExit(f"spiraltools not found ({e}): clone spiraldb beside spiralspider, or set SPIRALTOOLS to the "
                     "directory holding the spiraltools package (spiraldb/tools)") from e

__all__ = ["WORLDS", "archive", "world"]
