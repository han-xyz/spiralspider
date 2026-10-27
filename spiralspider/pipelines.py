"""The harvest of a crawl: per source, the quests listed and parsed, and the refusals and errors met."""
from .items import Listed
from .spiraltools_import import archive


class Harvest:
    def __init__(self, sources):
        self.counts = {name: {"enumerated": 0, "parsed": 0} for name in sources}
        self.found, self.records, self.blocked, self.errors = {}, {}, [], []

    def add(self, item):
        key = archive.title_norm(item.quest)
        if isinstance(item, Listed):
            self.counts[item.source]["enumerated"] += 1
            self.found.setdefault(key, item.quest)
            return
        self.records.setdefault(key, []).append((item.fields, item.provenance))
        self.counts[item.source]["parsed"] += 1

    def parsed_by(self, source):
        return {key for key, pairs in self.records.items() if any(p["source"] == source for _, p in pairs)}


class HarvestPipeline:
    """Every item a source spider yields goes into the harvest the crawl gave the spider."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_item(self, item):
        self.crawler.spider.harvest.add(item)
        return item
