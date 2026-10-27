"""Archived Wizard101 Central forum guides (web.archive.org copies): quest rewards.

A guide is read as bold quest names, each followed by its text up to the next bold name; a "<n> XP" and a
"<n> Gold" in that text are the reward. The guides are listed per world in GUIDES as archive URLs; the reading is an
assumption the fixture encodes and has not been checked against an archived guide.
"""
import html
import re
import urllib.parse

from ..items import Listed, Record
from ..middlewares import FETCHED
from . import SourceSpider, provenance, requested_url

# world name (as the spiraltools registry spells it) -> web.archive.org URLs of its quest guides
GUIDES = {
    # world: the Wayback copy of the Wizard101 Central forum guide (the live forum refuses automated clients).
    "Celestia": (
        "https://web.archive.org/web/20230930053505/https://www.wizard101central.com/forums/showthread.php?110487-Complete-Guide-to-Celestia-Quests",
    ),
}
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


class ForumGuide(SourceSpider):
    name = "forum_guide"

    async def start(self):
        for url in GUIDES.get(self.registered.name, ()):
            key = urllib.parse.urlsplit(url).path.strip("/")
            yield self.page_request(key, url, self.read_guide, errback=self.listing_failed)

    def read_guide(self, response):
        source = provenance(self.name, requested_url(response), response.meta[FETCHED])
        for name, reward in rewards(response.text).items():
            yield Listed(self.name, name)
            yield Record(self.name, name, {"name": name, "reward": reward}, source)
