"""Stage a complete ontology-versioned KG rebuild beside the active graph."""
from dataclasses import replace
from types import SimpleNamespace
from .clients import GraphBridge
from .graph import Finding
from .ranking import CRITERIA_VERSION
from .store import now
from .candidates import materialize


def rebuild_graph(app, group_id):
    if not group_id or group_id == app.settings.group_id:
        raise ValueError('Rebuild must use a new, non-active GRAPHITI_GROUP_ID')
    pending = [job for job in app.store.jobs() if job['kind'] in ('process', 'search')
               and job['status'] in ('queued', 'running')]
    if pending:
        raise RuntimeError(f'Rebuild paused: {len(pending)} process/search jobs are active')

    findings = sorted(app.store.list('findings'), key=lambda item: (item.get('published_at') or item['fetched_at'], item['id']))
    settings = replace(app.settings, group_id=group_id)
    build = app.store.get('graph_builds', group_id) or dict(id=group_id, status='building',
        ontology='startup-sourcing-v1', criteria_version=CRITERIA_VERSION,
        finding_count=len(findings), created_at=now())
    build.update(status='building', finding_count=len(findings), updated_at=now())
    app.store.put('graph_builds', build)

    bridge = GraphBridge(settings)
    candidate_ids = set()
    try:
        for record in findings:
            receipt_id = f'{group_id}:{record["id"]}'
            saved = app.store.get('graph_rebuild_receipts', receipt_id)
            if saved and saved.get('status') == 'materialized':
                candidate_ids.update(saved.get('candidate_ids', []))
                continue
            if saved and saved.get('status') == 'graph_processed':
                receipt = saved['receipt']
            else:
                finding = Finding.from_dict({**record, 'id': record.get('external_id') or record['id']})
                wrapped = SimpleNamespace(**finding.__dict__, episode_id=finding.episode_id)
                receipt = bridge.ingest(wrapped)
                receipt.update(group_id=group_id)
                saved = dict(id=receipt_id, group_id=group_id, finding_id=record['id'],
                    status='graph_processed', receipt=receipt, updated_at=now())
                app.store.put('graph_rebuild_receipts', saved)

            # Build a separate PostgreSQL projection. The current graph and finding receipts stay intact.
            ids = materialize(app, record, receipt, graph_group_id=group_id,
                              enqueue_evaluation=False, update_finding=False)
            candidate_ids.update(ids)
            saved.update(status='materialized', candidate_ids=ids, updated_at=now())
            app.store.put('graph_rebuild_receipts', saved)
    except Exception:
        build.update(status='failed', updated_at=now())
        app.store.put('graph_builds', build)
        raise
    finally:
        bridge.close()

    for candidate_id in sorted(candidate_ids):
        detail = app.candidate_detail(candidate_id)
        assessment = detail.get('assessment')
        current = bool(assessment and assessment.get('criteria_version') == CRITERIA_VERSION
                       and assessment.get('profile_version') == detail['profile_version'])
        if not current:
            app.queue('evaluate', candidate_id)
    nodes = [n for n in app.store.list('graph_nodes') if n.get('group_id') == group_id]
    edges = [e for e in app.store.list('graph_edges') if e.get('group_id') == group_id]
    build.update(status='complete', node_count=len(nodes), edge_count=len(edges),
        candidate_count=len(candidate_ids), completed_at=now(), updated_at=now())
    app.store.put('graph_builds', build)
    return {key: build[key] for key in ('id', 'status', 'finding_count', 'node_count', 'edge_count', 'candidate_count')}


def rebuild_from_neon(app):
    """Build a candidate-focused KG while retaining every Neon source record."""
    import os
    import hashlib
    import json
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from .adapter_bridge import read_adapter_records
    from .clients import OpenAIDecisionRelevance, OpenAIModels
    from .graph import Finding
    from .store import now

    # Graphiti bounds internal concurrency through this semaphore. Respect an
    # explicit deployment override; otherwise use a moderate parallel level.
    os.environ.setdefault('SEMAPHORE_LIMIT', '2')
    source_data = read_adapter_records(app.settings.database_url, limit=1000)
    if not source_data['items']:
        raise RuntimeError('No valid adapter source records found; nothing was cleared')
    mapped = source_data['items']

    # Gate before clearing anything. The Decision API sees the complete original payload
    # and all linked Neon context. The generative model only verifies positive candidates.
    import asyncio
    import os
    models = OpenAIModels(app.settings)
    decision_model = os.environ.get('OPENAI_DECISIONS_MODEL', '')
    if app.settings.decision_provider != 'openai' or not decision_model:
        raise RuntimeError('Candidate preselection requires the configured OpenAI Decision API')
    gate_model = f'openai-decisions:{decision_model}'
    relevance = {}
    existing_relevance = {row['id']: row for row in app.store.list('graph_relevance')}
    context_hashes = {
        item['external_id']: hashlib.sha256(json.dumps(
            item['decision_context'], ensure_ascii=False).encode()).hexdigest()
        for item in mapped
    }
    for item in mapped:
        cached = existing_relevance.get(item['external_id'])
        if (cached and cached.get('context_hash') == context_hashes[item['external_id']]
                and cached.get('model') == gate_model):
            relevance[item['external_id']] = {key: cached[key] for key in
                ('id', 'relevant', 'evidence_type', 'candidate_name', 'reason',
                 'evidence_quote', 'model', 'decision', 'confidence')}
    pending = [item for item in mapped if item['external_id'] not in relevance]
    max_batch_chars = 120000
    batches, current, current_chars = [], [], 0
    for item in pending:
        size = len(item['decision_context'])
        if current and current_chars + size > max_batch_chars:
            batches.append(current)
            current, current_chars = [], 0
        current.append(item)
        current_chars += size
    if current:
        batches.append(current)
    decision_gate = OpenAIDecisionRelevance(app.settings, max_concurrency=2)
    decision_loop = asyncio.new_event_loop()
    try:
        decision_batches = decision_loop.run_until_complete(decision_gate.classify_all(batches))
    finally:
        decision_loop.run_until_complete(decision_gate.close())
        decision_loop.close()
    provisional = {decision['id']: decision
                   for batch_decisions in decision_batches for decision in batch_decisions}
    positive_items = [item for item in pending if provisional[item['external_id']]['relevant']]
    validation = {}
    if positive_items:
        from concurrent.futures import ThreadPoolExecutor
        validation_batches = [positive_items[offset:offset + 10]
                             for offset in range(0, len(positive_items), 10)]
        def validate(batch):
            inputs = [{'id': item['external_id'], 'context': item['relevance_context']} for item in batch]
            return models.classify_candidate_relevance(inputs)
        with ThreadPoolExecutor(max_workers=4) as executor:
            for decisions in executor.map(validate, validation_batches):
                for decision in decisions:
                    validation[decision['id']] = decision
    for item in pending:
        selected = provisional[item['external_id']]
        checked = validation.get(item['external_id'])
        if not selected['relevant']:
            final = dict(selected, evidence_type='irrelevant', candidate_name='', evidence_quote='')
        elif checked:
            final = dict(selected, relevant=checked['relevant'],
                evidence_type=checked['evidence_type'], candidate_name=checked['candidate_name'],
                evidence_quote=checked['evidence_quote'],
                reason=checked['reason'] if checked['relevant'] else
                    'Decision API selected this record, but source-evidence validation rejected it.',
                validator_model=checked['model'])
        else:
            raise RuntimeError('Decision API selected a candidate without a source-evidence validation')
        relevance[item['external_id']] = final
    with app.store.transaction() as connection:
        for item in mapped:
            decision = relevance[item['external_id']]
            app.store.put('graph_relevance', dict(decision,
                id=item['external_id'], context_hash=context_hashes[item['external_id']],
                source_name=item['source_name'], status='classified', updated_at=now()), connection)
    relevant = [item for item in mapped if relevance[item['external_id']]['relevant']]

    finding_objects = []
    for item in relevant:
        finding = Finding.from_dict({
            'id': item['external_id'], 'source': item['source_id'], 'url': item['url'],
            'title': item['title'], 'text': item['text'], 'fetched_at': item['fetched_at'],
            'published_at': item.get('published_at'),
        })
        finding_objects.append(SimpleNamespace(**finding.__dict__, episode_id=finding.episode_id))

    bridge = GraphBridge(app.settings)
    client = bridge._live()
    neo4j_nodes_before, _, _ = bridge.loop.run_until_complete(
        client.driver.execute_query('MATCH (n) RETURN count(n) AS n'))
    relationships, _, _ = bridge.loop.run_until_complete(
        client.driver.execute_query('MATCH ()-[r]->() RETURN count(r) AS n'))
    bridge.loop.run_until_complete(client.driver.execute_query('MATCH (n) DETACH DELETE n'))
    remaining, _, _ = bridge.loop.run_until_complete(
        client.driver.execute_query('MATCH (n) RETURN count(n) AS n'))
    if remaining[0]['n']:
        bridge.close()
        raise RuntimeError('Neo4j reset verification failed')

    with app.store.transaction() as connection:
        old_records = app.store.sql(connection, 'SELECT count(*) AS n FROM records').fetchone()['n']
        old_jobs = app.store.sql(connection, 'SELECT count(*) AS n FROM jobs').fetchone()['n']
        old_leases = app.store.sql(connection, 'SELECT count(*) AS n FROM leases').fetchone()['n']
        app.store.sql(connection, 'DELETE FROM jobs')
        app.store.sql(connection, 'DELETE FROM leases')
        app.store.sql(connection, "DELETE FROM records WHERE kind <> 'graph_relevance'")

    try:
        source_ids = set()
        finder_records = {}
        with app.store.transaction() as connection:
            for item in mapped:
                decision = relevance[item['external_id']]
                gate = dict(decision, id=item['external_id'], source_name=item['source_name'],
                    status='relevant_pending' if decision['relevant'] else 'excluded',
                    context_hash=context_hashes[item['external_id']], updated_at=now())
                app.store.put('graph_relevance', gate, connection)
            for item in relevant:
                if item['source_id'] not in source_ids:
                    source_ids.add(item['source_id'])
                    host = urlparse(item['source_url']).hostname
                    app.store.put('sources', dict(id=item['source_id'], name=item['source_name'],
                        url=item['source_url'], kind='manual', enabled=False, allowed_hosts=[host],
                        created_at=item['fetched_at'], updated_at=item['fetched_at']), connection)
                record = app.import_finding(item, connection)
                finder_records[item['external_id']] = record
                gate = app.store.get('graph_relevance', item['external_id'], connection)
                gate.update(finding_id=record['id'], updated_at=now())
                app.store.put('graph_relevance', gate, connection)

        receipts = bridge.ingest_batch(finding_objects) if finding_objects else []
        if len(receipts) != len(relevant):
            raise RuntimeError('Graphiti bulk result count does not match source records')
        for item, receipt in zip(relevant, receipts, strict=True):
            record = finder_records[item['external_id']]
            if record['external_id'] != receipt['finding_id']:
                raise RuntimeError('Graphiti bulk receipt was paired with the wrong source record')
            venture_ids = {node['id'] for node in receipt['nodes']
                           if 'StartupVenture' in node.get('labels', [])}
            if not venture_ids:
                gate = app.store.get('graph_relevance', item['external_id'])
                gate.update(status='no_venture_extracted', updated_at=now())
                app.store.put('graph_relevance', gate)
                record.update(status='excluded_no_startup_entity', candidate_ids=[], updated_at=now())
                app.store.put('findings', record)
                continue
            keep_ids = set(venture_ids)
            for edge in receipt['edges']:
                if edge['source'] in venture_ids:
                    keep_ids.add(edge['target'])
                if edge['target'] in venture_ids:
                    keep_ids.add(edge['source'])
            candidate_receipt = dict(receipt,
                nodes=[node for node in receipt['nodes'] if node['id'] in keep_ids],
                edges=[edge for edge in receipt['edges']
                       if edge['source'] in keep_ids and edge['target'] in keep_ids
                       and (edge['source'] in venture_ids or edge['target'] in venture_ids)])
            materialize(app, record, candidate_receipt, graph_group_id=app.settings.group_id,
                        enqueue_evaluation=False, update_finding=True)

            gate = app.store.get('graph_relevance', item['external_id'])
            gate.update(status='materialized', venture_node_ids=sorted(venture_ids), updated_at=now())
            app.store.put('graph_relevance', gate)

        # Graphiti can still emit incidental paper/author/topic entities from a relevant
        # source. Keep only venture anchors and entities one edge away from an anchor.
        bridge.loop.run_until_complete(client.driver.execute_query('''
            MATCH (n:Entity {group_id: $group})
            WHERE NOT 'StartupVenture' IN labels(n)
              AND NOT EXISTS {
                MATCH (n)-[:RELATES_TO]-(v:Entity {group_id: $group})
                WHERE 'StartupVenture' IN labels(v)
              }
            DETACH DELETE n
        ''', group=app.settings.group_id))

        nodes = [n for n in app.store.list('graph_nodes') if n.get('group_id') == app.settings.group_id]
        edges = [e for e in app.store.list('graph_edges') if e.get('group_id') == app.settings.group_id]
        candidates = app.store.list('candidates')
        return {'source_records': source_data['read'], 'skipped': source_data['skipped'],
                'relevant_source_records': len(relevant),
                'excluded_source_records': len(mapped) - len(relevant),
                'parallelism': int(os.getenv('SEMAPHORE_LIMIT', '8')),
                'deleted_neo4j_nodes': neo4j_nodes_before[0]['n'],
                'deleted_neo4j_relationships': relationships[0]['n'],
                'deleted_finder_records': old_records, 'deleted_jobs': old_jobs,
                'deleted_leases': old_leases, 'nodes': len(nodes), 'edges': len(edges),
                'candidates': len(candidates), 'active_group': app.settings.group_id,
                'neon_source_tables_preserved': True}
    finally:
        bridge.close()

