import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from context import ROOT
from spiralspider.cli import main, write_results
from spiralspider.items import Listed, Record
from spiralspider.pipelines import Harvest
from spiralspider.spiraltools_import import WORLDS, world

# A Twisted reactor runs once per process, so the crawl runs in a process of its own.
TWO_SPIDERS = f"""
import sys
sys.path.insert(0, {ROOT!r})
import scrapy
from spiralspider.cli import run_one_after_another

events = []


class Stub(scrapy.Spider):
    async def start(self):
        events.append("open " + self.name)
        return
        yield

    def closed(self, reason):
        events.append("close " + self.name)


class One(Stub):
    name = "one"


class Two(Stub):
    name = "two"


run_one_after_another({{"LOG_ENABLED": False}}, [(One, {{}}), (Two, {{}})])
print(events)
"""


class OneAfterAnother(unittest.TestCase):
    def test_each_spider_opens_and_closes_before_the_next_one(self):
        run = subprocess.run([sys.executable, "-I", "-c", TWO_SPIDERS], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.stdout.strip(), "['open one', 'close one', 'open two', 'close two']", run.stderr[-2000:])


class Results(unittest.TestCase):
    def test_record_without_a_quest_name_is_an_error_not_a_crash(self):
        harvest = Harvest(["folio"])
        source = {"source": "folio", "url": "https://wizard101folio.com/dragonspyre-quest-tree", "fetched": "20261027"}
        for quest, fields in (("Bad Blood", {"name": "Bad Blood", "order": 1}), ("", {"name": "", "order": 2})):
            harvest.add(Listed("folio", quest))
            harvest.add(Record("folio", quest, fields, source))
        report = write_results(world("DragonSpire"), harvest, tempfile.mkdtemp())
        self.assertEqual(report["parsed"], 1)
        self.assertEqual([(e["source"], e["url"]) for e in report["errors"]], [("folio", source["url"])])


if __name__ == "__main__":
    unittest.main()


class Assist(unittest.TestCase):
    def test_runs_for_the_named_worlds_or_all_of_them(self):
        with mock.patch("spiralspider.assist.run") as run:
            main(["assist", "celestia", "Zafaria", "--cache", "c", "--profile", "p"])
            main(["assist", "--all-worlds"])
        self.assertEqual(run.call_args_list[0], mock.call([world("Celestia"), world("Zafaria")], "c", "p"))
        self.assertEqual(run.call_args_list[1].args[0], list(WORLDS))

    def test_needs_a_world(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            main(["assist"])
