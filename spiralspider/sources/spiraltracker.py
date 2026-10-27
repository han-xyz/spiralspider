"""spiraltracker.com/<world>: quest order and goal types."""
import re

from .listing import ListingSource, quests_of, text_of

ROW = re.compile(r'<div id="quest-\d+"[^>]*class="quest-row[^"]*"[^>]*>(.*?)'
                 r'(?=<div id="quest-\d+"[^>]*class="quest-row|<div id="area-|<footer|\Z)', re.S)
NAME = re.compile(r'<a class="quest-name[^"]*"[^>]*>(.*?)</a>', re.S)
BADGE = re.compile(r'class="step-badge step-([a-z_]+)')


def listed_quests(page):
    """A quest row's name link and its step badges (talk, explore, boss, mob, interact, ...), as the 2026-10 pages
    write them."""
    rows = []
    for row in ROW.findall(page):
        name = NAME.search(row)
        rows.append((text_of(name.group(1)) if name else "", BADGE.findall(row)))
    return quests_of(rows)


class SpiralTracker(ListingSource):
    name = "spiraltracker"
    url_template = "https://spiraltracker.com/{}"
    listed_quests = staticmethod(listed_quests)
