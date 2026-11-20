"""Optional Graphiti Decision routing, using the upstream LLMRuntime API.

Provider/model availability must be checked for the installed Graphiti release.
Requested but unavailable integration fails explicitly, never falls back silently.
"""
import os


def create_graphiti(settings):
    from graphiti_core import Graphiti
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    driver = Neo4jDriver(settings.neo4j_uri, settings.neo4j_user,
                         settings.neo4j_password, database=settings.neo4j_database)
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_client import OpenAIClient
    generative = OpenAIClient(config=LLMConfig(api_key=settings.openai_key,
                                             model=settings.model, small_model=settings.model))
    if settings.decision_provider == 'off':
        return Graphiti(graph_driver=driver, llm_client=generative)
    try:
        from graphiti_core.llm_client import LLMRuntime, LLMTransport, PromptRoutes
        if settings.decision_provider == 'jev':
            from graphiti_core.llm_client import JevClient, jev_prompt_overrides
            decision_id = os.getenv('JEV_MODEL', 'jev-latest')
            transport = LLMTransport(JevClient(), models=[decision_id])
            decision = transport.model(decision_id, prompt_overrides=jev_prompt_overrides())
        else:
            from graphiti_core.llm_client import OpenAIDecisionsClient, openai_decisions_prompt_overrides
            decision_id = os.environ['OPENAI_DECISIONS_MODEL']
            transport = LLMTransport(OpenAIDecisionsClient(), models=[decision_id])
            decision = transport.model(decision_id, prompt_overrides=openai_decisions_prompt_overrides())
        base = LLMTransport(generative, models=[settings.model])
        runtime = LLMRuntime(model=base.model(settings.model), routes=PromptRoutes(
            dedupe_nodes=PromptRoutes.DedupeNodes(nodes=decision),
            dedupe_edges=PromptRoutes.DedupeEdges(resolve_edge=decision)))
    except (ImportError, AttributeError) as exc:
        raise RuntimeError('Graphiti lacks requested Decision API; install a compatible version or configure GRAPHITI_CLIENT_FACTORY.') from exc
    return Graphiti(graph_driver=driver, llm_runtime=runtime)
