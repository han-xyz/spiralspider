import json
import os
import tempfile
import unittest

import context  # noqa: F401
from spiralspider.spiraltools_import import world
from spiralspider.specs import SpecError, build_spec, validate, write_spec

CELESTIA = world("Celestia")
WIKI = {"source": "wiki_live", "url": "https://wiki.wizard101central.com/wiki/Quest:Deeper_and_Deeper",
        "fetched": "20261027000000"}
MERGED = {
    "fields": {"name": "Deeper and Deeper", "prequests": ["Door to the Stars", "Unlisted Quest"],
               "giver": "Edith Benchley", "mainline": True, "goals": ["@Talk to Dalton Prescott"],
               "hand_in": "Dalton Prescott", "reward": {"gold": 30, "xp": 560}, "leads_to": ["Survivors"]},
    "provenance": {field: WIKI for field in ("name", "prequests", "giver", "mainline", "goals", "hand_in", "reward",
                                             "leads_to")},
}
IDS = {"doortothestars": "CL-Q-doortothestars", "survivors": "CL-Q-survivors"}


class SpecWriter(unittest.TestCase):
    def test_spec_carries_what_the_sources_give_in_the_schema(self):
        spec = build_spec(CELESTIA, MERGED, IDS)
        self.assertEqual(spec["id"], "CL-Q-deeperanddeeper")
        self.assertEqual(spec["requires"], ["CL-Q-doortothestars"])
        self.assertEqual(spec["successors"], ["CL-Q-survivors"])
        self.assertEqual(spec["reward"], {"xp": 560, "gold": 30})
        self.assertEqual((spec["mainline"], spec["level"]), (True, 48))
        self.assertEqual(spec["source"]["reward"], WIKI)
        validate(spec)

    def test_what_needs_the_client_is_listed_as_blocking(self):
        review = build_spec(CELESTIA, MERGED, IDS)["needs_review"]
        blocking = {item["field"] for item in review if item["blocking"]}
        self.assertEqual(blocking, {"lang", "giver", "goals"})
        self.assertIn({"field": "requires", "value": "Unlisted Quest", "blocking": False}, review)

    def test_spec_with_a_blocking_gap_is_written_under_blocked(self):
        spec = build_spec(CELESTIA, MERGED, IDS)
        with tempfile.TemporaryDirectory() as out:
            path = write_spec(out, spec)
            self.assertEqual(path, os.path.join(out, "blocked", "CL-Q-deeperanddeeper.json"))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), spec)

    def test_field_outside_the_schema_is_refused(self):
        with self.assertRaises(SpecError):
            validate({"id": "CL-Q-x", "requires": [], "colour": "blue"})

    def test_goal_missing_what_its_type_needs_is_refused(self):
        with self.assertRaises(SpecError):
            validate({"id": "CL-Q-x", "goals": [{"type": "bounty", "mobs": ["CL-Eel-Green-R9.AdjRef"]}]})


if __name__ == "__main__":
    unittest.main()
