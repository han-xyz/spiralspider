import subprocess
import sys
import unittest

from context import ROOT

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


if __name__ == "__main__":
    unittest.main()
