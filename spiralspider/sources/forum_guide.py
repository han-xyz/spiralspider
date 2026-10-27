"""Archived Wizard101 Central forum guides (web.archive.org copies): quest rewards.

A guide is read as bold quest names, each followed by its text up to the next bold name; a "<n> XP" and a
"<n> Gold" in that text are the reward. The guides are listed per world in GUIDES as archive URLs; the reading is an
assumption the fixture encodes and has not been checked against an archived guide.
"""
import html
import re
import urllib.parse

from ..spiraltools_import import archive, world
from . import Raw, fetch_cached, provenance

# world name (as the spiraltools registry spells it) -> web.archive.org URLs of its quest guides
GUIDES = {}
BOLD = re.compile(r"<b>(.*?)</b>(.*?)(?=<b>|$)", re.S)
XP = re.compile(r"([\d,]+)\s*XP\b", re.I)
GOLD = re.compile(r"([\d,]+)\s*Gold\b", re.I)


def rewards(page):
    """quest name -> {"xp", "gold"} for every bold name whose text gives both."""
    found = {}
    for name, body in BOLD.findall(page):
        text = html.unescape(re.sub(r"<[^>]+>", " ", body))
        xp, gold = XP.search(text), GOLD.search(text)
        if xp and gold:
            found[" ".join(html.unescape(re.sub(r"<[^>]+>", "", name)).split())] = {
                "xp": int(xp.group(1).replace(",", "")), "gold": int(gold.group(1).replace(",", ""))}
    return found


class ForumGuide:
    name = "forum_guide"

    def __init__(self, gate, cache):
        self.gate, self.cache = gate, cache
        self.guides = {}

    def enumerate(self, world_name):
        names = []
        for url in GUIDES.get(world(world_name).name, ()):
            key = urllib.parse.urlsplit(url).path.strip("/")
            fetched = fetch_cached(self.gate, self.name, self.cache, key, url)
            if fetched is None:
                continue
            for name in rewards(fetched[1]):
                self.guides.setdefault(name, (url, *fetched))
                names.append(name)
        return names

    def fetch(self, quest):
        if quest not in self.guides:
            return None
        url, stamp, text = self.guides[quest]
        return Raw(quest, text, provenance(self.name, url, stamp))

    def parse(self, raw):
        wanted = archive.title_norm(raw.quest)
        reward = next((r for name, r in rewards(raw.text).items() if archive.title_norm(name) == wanted), None)
        return {"name": raw.quest, "reward": reward} if reward else None
