"""Configuration without import-time network calls or secret logging."""
from dataclasses import dataclass
import os
from pathlib import Path


def load_env(path='.env'):
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    mode: str = 'demo'
    database_url: str = 'sqlite:///data/demo.sqlite3'
    host: str = '127.0.0.1'
    port: int = 8000
    api_token: str = ''
    cors_origins: tuple = ('http://localhost:5173', 'http://localhost:3000')
    openai_key: str = ''
    model: str = 'gpt-4.1-mini'
    neo4j_uri: str = 'bolt://localhost:7687'
    neo4j_user: str = 'neo4j'
    neo4j_password: str = ''
    group_id: str = 'startup_finder_de'
    graphiti_factory: str = ''
    decision_provider: str = 'off'
    lease_seconds: int = 600

    @classmethod
    def from_env(cls):
        load_env()
        mode = os.getenv('APP_MODE', 'demo')
        if mode not in ('demo', 'live'):
            raise ValueError('APP_MODE must be demo or live')
        settings = cls(mode=mode, database_url=os.getenv('DATABASE_URL', 'sqlite:///data/demo.sqlite3'),
                       host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8000')),
                       api_token=os.getenv('API_TOKEN', ''),
                       cors_origins=tuple(x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://localhost:3000').split(',') if x.strip()),
                       openai_key=os.getenv('OPENAI_API_KEY', ''), model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
                       neo4j_uri=os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
                       neo4j_user=os.getenv('NEO4J_USER', 'neo4j'), neo4j_password=os.getenv('NEO4J_PASSWORD', ''),
                       group_id=os.getenv('GRAPHITI_GROUP_ID', 'startup_finder_de'),
                       graphiti_factory=os.getenv('GRAPHITI_CLIENT_FACTORY', ''),
                       decision_provider=os.getenv('DECISION_PROVIDER', 'off'))
        if settings.mode == 'live':
            if not settings.database_url.startswith(('postgresql://', 'postgres://')):
                raise ValueError('Live mode requires PostgreSQL DATABASE_URL')
            if not settings.openai_key or not settings.neo4j_password or not settings.api_token:
                raise ValueError('Live mode requires OPENAI_API_KEY, NEO4J_PASSWORD and API_TOKEN')
        if settings.decision_provider not in ('off', 'jev', 'openai'):
            raise ValueError('DECISION_PROVIDER must be off, jev or openai')
        if settings.decision_provider == 'jev' and not os.getenv('JEV_API_KEY'):
            raise ValueError('JEV_API_KEY required for Jev routing')
        if settings.decision_provider == 'openai' and not os.getenv('OPENAI_DECISIONS_MODEL'):
            raise ValueError('Set the model ID supplied with your OpenAI Decisions access')
        return settings
