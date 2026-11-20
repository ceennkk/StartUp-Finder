"""Graphiti boundary. The caller owns source DB/job state and serializes ingestion."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class Finding:
    id: str
    source: str
    url: str
    title: str
    text: str
    fetched_at: datetime
    published_at: datetime | None = None

    def __post_init__(self):
        for key in ("id", "source", "title", "text"):
            if not getattr(self, key).strip():
                raise ValueError(f"{key} must not be empty")
        parsed = urlparse(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("absolute HTTP(S) URL required")
        for value in (self.fetched_at, self.published_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("timezone required")

    @classmethod
    def from_dict(cls, data):
        values = {key: data[key] for key in ("id", "source", "url", "title", "text")}
        values["fetched_at"] = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))
        raw = data.get("published_at")
        values["published_at"] = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None
        return cls(**values)

    def episode_id(self, group):
        body = json.dumps([self.url, self.title, self.text,
                           self.published_at.isoformat() if self.published_at else None])
        digest = hashlib.sha256(body.encode()).hexdigest()
        return str(uuid5(NAMESPACE_URL, f"{group}:{self.source}:{self.id}:{digest}"))


class GraphService:
    def __init__(self, client, group_id="startup_finder_de"):
        self.client = client
        self.group_id = group_id

    async def initialize(self):
        await self.client.build_indices_and_constraints()

    async def ingest(self, finding):
        from graphiti_core.nodes import EpisodeType
        records, _, _ = await self.client.driver.execute_query(
            'MATCH (e:Episodic {group_id: $group_id}) WHERE e.source_description CONTAINS $finding_id RETURN e.uuid AS uuid',
            group_id=self.group_id, finding_id=f'"finding_id": "{finding.id}"')
        if records:
            return {"finding_id": finding.id, "episode_id": records[0]["uuid"], "status": "unchanged"}
        from graphiti_core.utils.bulk_utils import RawEpisode
        from .ontology import EDGE_TYPES, EDGE_TYPE_MAP, ENTITY_TYPES, EXTRACTION_INSTRUCTIONS
        result = await self.client.add_episode_bulk(
            bulk_episodes=[RawEpisode(name=finding.title, content=finding.text, source=EpisodeType.text,
                source_description=json.dumps({"finding_id": finding.id, "url": finding.url,
                                               "source": finding.source, "fetched_at": finding.fetched_at.isoformat()}),
                reference_time=finding.published_at or finding.fetched_at)],
            group_id=self.group_id, entity_types=ENTITY_TYPES, edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP, strict_edge_types=True,
            custom_extraction_instructions=EXTRACTION_INSTRUCTIONS)
        return {"finding_id": finding.id, "episode_id": result.episodes[0].uuid, "group_id": self.group_id,
                "status": "processed", "node_ids": [n.uuid for n in result.nodes],
                "edge_ids": [e.uuid for e in result.edges]}

    async def search(self, query):
        edges = await self.client.search(query, group_ids=[self.group_id])
        return [{"id": e.uuid, "fact": e.fact, "episode_ids": e.episodes,
                 "source_node_id": e.source_node_uuid, "target_node_id": e.target_node_uuid}
                for e in edges]

    async def close(self):
        await self.client.close()
