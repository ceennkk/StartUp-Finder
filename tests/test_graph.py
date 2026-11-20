import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, patch
from startup_finder.graph import Finding, GraphService


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.finding = Finding("1", "demo", "https://example.org", "Team", "Team in Aachen",
                               datetime(2026, 11, 20, tzinfo=timezone.utc))

    def test_versions_and_groups_have_distinct_ids(self):
        original = self.finding.episode_id("de")
        self.assertEqual(original, replace(self.finding, fetched_at=datetime.now(timezone.utc)).episode_id("de"))
        self.assertNotEqual(original, replace(self.finding, text="Changed").episode_id("de"))
        self.assertNotEqual(original, self.finding.episode_id("other"))

    def test_reject_naive_timestamp(self):
        with self.assertRaises(ValueError):
            replace(self.finding, fetched_at=datetime(2026, 11, 20))

    def test_ingestion_and_repeat(self):
        client = SimpleNamespace(driver=SimpleNamespace(execute_query=AsyncMock(return_value=([], None, None))),
                                 add_episode_bulk=AsyncMock(return_value=SimpleNamespace(
                                     episodes=[SimpleNamespace(uuid="episode")], nodes=[], edges=[])))
        nodes = SimpleNamespace(EpisodeType=SimpleNamespace(text="text"))
        raw_episode = ModuleType("graphiti_core.utils.bulk_utils")
        raw_episode.RawEpisode = lambda **kwargs: SimpleNamespace(**kwargs)
        with patch.dict(sys.modules, {"graphiti_core.nodes": nodes,
                                      "graphiti_core.utils.bulk_utils": raw_episode}):
            result = asyncio.run(GraphService(client).ingest(self.finding))
            self.assertEqual(result["status"], "processed")
            kwargs = client.add_episode_bulk.call_args.kwargs
            self.assertEqual(kwargs["bulk_episodes"][0].reference_time, self.finding.fetched_at)
            self.assertIn(self.finding.url, kwargs["bulk_episodes"][0].source_description)
            self.assertTrue(kwargs["strict_edge_types"])
            client.driver.execute_query.return_value = ([{"uuid": "existing"}], None, None)
            result = asyncio.run(GraphService(client).ingest(self.finding))
            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(client.add_episode_bulk.await_count, 1)

    def test_failure_is_propagated(self):
        client = SimpleNamespace(driver=SimpleNamespace(execute_query=AsyncMock(side_effect=RuntimeError("offline"))))
        nodes = SimpleNamespace(EpisodeType=SimpleNamespace(text="text"))
        with patch.dict(sys.modules, {"graphiti_core.nodes": nodes}):
            with self.assertRaises(RuntimeError):
                asyncio.run(GraphService(client).ingest(self.finding))


if __name__ == "__main__":
    unittest.main()
