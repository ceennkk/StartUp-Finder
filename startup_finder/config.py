"""Configuration without import-time network calls or secret logging."""
from dataclasses import dataclass
import os
import ipaddress
from pathlib import Path


def load_env(path='.env'):
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    database_url: str = ''
    host: str = '127.0.0.1'
    port: int = 8000
    api_token: str = ''
    cors_origins: tuple = ('http://localhost:5173', 'http://localhost:3000')
    openai_key: str = ''
    model: str = 'gpt-6-luna'
    neo4j_uri: str = 'bolt://localhost:7687'
    neo4j_user: str = 'neo4j'
    neo4j_password: str = ''
    neo4j_database: str = 'neo4j'
    group_id: str = 'startup_finder_de'
    graphiti_factory: str = ''
    decision_provider: str = 'off'
    lease_seconds: int = 600

    @classmethod
    def from_env(cls):
        load_env()
        if os.getenv('APP_MODE', 'live').casefold() != 'live':
            raise ValueError('Only production mode is supported; remove APP_MODE or set APP_MODE=live')
        settings = cls(database_url=os.getenv('DATABASE_URL', ''),
                       host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8000')),
                       api_token=os.getenv('API_TOKEN', ''),
                       cors_origins=tuple(x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://localhost:3000').split(',') if x.strip()),
                       openai_key=os.getenv('OPENAI_API_KEY', ''), model=os.getenv('OPENAI_MODEL', 'gpt-6-luna'),
                       neo4j_uri=os.getenv('NEO4J_URI', ''),
                       neo4j_user=os.getenv('NEO4J_USER', ''), neo4j_password=os.getenv('NEO4J_PASSWORD', ''),
                       neo4j_database=os.getenv('NEO4J_DATABASE', 'neo4j'),
                       group_id=os.getenv('GRAPHITI_GROUP_ID', 'startup_finder_de'),
                       graphiti_factory=os.getenv('GRAPHITI_CLIENT_FACTORY', ''),
                       decision_provider=os.getenv('DECISION_PROVIDER', 'off'))
        if not settings.database_url.startswith(('postgresql://', 'postgres://')):
            raise ValueError('Production requires a PostgreSQL DATABASE_URL')
        missing = [name for name, value in (
            ('OPENAI_API_KEY', settings.openai_key),
            ('NEO4J_URI', settings.neo4j_uri),
            ('NEO4J_USER', settings.neo4j_user),
            ('NEO4J_PASSWORD', settings.neo4j_password),
        ) if not value]
        if not settings.api_token:
            try:
                local_only = ipaddress.ip_address(settings.host).is_loopback
            except ValueError:
                local_only = settings.host.casefold() == 'localhost'
            if not local_only:
                missing.append('API_TOKEN (required when HOST is not loopback)')
        if missing:
            raise ValueError('Production configuration missing: ' + ', '.join(missing))
        if settings.decision_provider not in ('off', 'jev', 'openai'):
            raise ValueError('DECISION_PROVIDER must be off, jev or openai')
        if settings.decision_provider == 'jev' and not os.getenv('JEV_API_KEY'):
            raise ValueError('JEV_API_KEY required for Jev routing')
        if settings.decision_provider == 'openai' and not os.getenv('OPENAI_DECISIONS_MODEL'):
            raise ValueError('Set the model ID supplied with your OpenAI Decisions access')
        return settings
