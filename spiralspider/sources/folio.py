"""wizard101folio.com/<world>-quest-tree: quest order and goals."""
import re

from .listing import ListingSource, quests_of, text_of

ROW = re.compile(r"<tr>\s*<td>\s*\d+\s*</td>\s*<td>(.*?)</td>\s*<td[^>]*>(.*?)</td>", re.S)
COUNT = re.compile(r"\bx\d+\b")


def listed_quests(page):
    """The quest tables' rows (#, quest name, actions required joined by "+", details), as the 2026-10 pages write
    them; an action loses its count ("Talk x2" is talk)."""
    rows = []
    for name, actions in ROW.findall(page):
        kinds = [" ".join(COUNT.sub("", action).split()).lower() for action in text_of(actions).split("+")]
        rows.append((text_of(name), [kind for kind in kinds if kind]))
    return quests_of(rows)


class Folio(ListingSource):
    name = "folio"
    url_template = "https://wizard101folio.com/{}-quest-tree"
    listed_quests = staticmethod(listed_quests)
