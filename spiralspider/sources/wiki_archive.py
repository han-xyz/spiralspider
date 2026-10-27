"""The Internet Archive's copies of the wiki: the CDX index and the category captures, then each quest's snapshot.

The enumeration and the cache are spiraltools' own (`quests/archive.py`), with every request sent through the crawl's
gate, so `spiraltools.py archive parse <World> --cache <cache>/wiki_archive` reads the same cache.
"""
import urllib.error

from ..spiraltools_import import archive, world
from . import Raw, provenance


class GatedArchive:
    """spiraltools' Archive interface (get(url) -> (final url, bytes)) over the gate; a non-200 is an HTTPError."""

    def __init__(self, gate, source):
        self.gate, self.source = gate, source

    def get(self, url):
        response = self.gate.fetch(self.source, url)
        if response.status != 200:
            raise urllib.error.HTTPError(url, response.status, f"HTTP {response.status}", None, None)
        return response.url, response.text.encode("utf-8")


class WikiArchive:
    name = "wiki_archive"

    def __init__(self, gate, cache):
        self.cache = cache
        self.archive = GatedArchive(gate, self.name)
        self.entries = {}

    def enumerate(self, world_name):
        registered = world(world_name)
        archive.enumerate_world(self.archive, self.cache, registered)
        index = archive.load_index(self.cache, registered.name)
        self.entries = {entry["name"]: entry for entry in index if not entry.get("missing_snapshot")}
        return list(self.entries)

    def fetch(self, quest):
        """The newest raw snapshot, else the CDX capture raw, else that capture in the playback form."""
        entry = self.entries[quest]
        for raw, at in ((True, archive.NEWEST), (True, entry["timestamp"]), (False, entry["timestamp"])):
            try:
                stamp, text = archive.fetch_page(self.archive, self.cache, entry["page"], raw=raw, at=at)
            except urllib.error.HTTPError:
                continue
            url = f"{archive.ARCHIVE}{stamp}{'id_' if raw else ''}/{archive.WIKI}{entry['page']}"
            return Raw(quest, text, provenance(self.name, url, stamp))
        return None

    def parse(self, raw):
        return {"name": raw.quest, **archive.read_page(raw.text)}
