"""Materialize candidate profiles from resolved graph nodes and their provenance."""
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5
from .store import now, uid


def materialize(app, finding, receipt, graph_group_id='startup_finder_de',
                enqueue_evaluation=True, update_finding=True):
    store = app.store
    ids = []
    with store.transaction() as c:
        for node in receipt['nodes']:
            existing_node = store.get('graph_nodes', node['id'], c) or {}
            store.put('graph_nodes', dict(existing_node, **node, group_id=graph_group_id), c)
        for edge in receipt['edges']:
            old = store.get('graph_edges', edge['id'], c) or {}
            edge = dict(edge, group_id=graph_group_id,
                        episode_ids=sorted(set(old.get('episode_ids', []) + edge.get('episode_ids', []))))
            store.put('graph_edges', edge, c)
        for node in receipt['nodes']:
            if 'StartupVenture' not in node.get('labels', []):
                continue
            attrs = node.get('attributes') or node
            record_id = node['id']
            previous = store.get('candidates', record_id, c)
            legacy = None
            if not previous:
                normalized = node['name'].strip().casefold()
                legacy = next((candidate for candidate in store.list('candidates', c)
                    if candidate.get('graph_group_id', 'startup_finder_de') != graph_group_id
                    and candidate.get('name', '').strip().casefold() == normalized), None)
            candidate = previous or dict(id=record_id, graph_node_id=node['id'], name=node['name'],
                description='', website='', location='', germany_status='unknown', entity_type='venture',
                people=[], signals=[], open_questions=[], status=legacy.get('status', 'new') if legacy else 'new',
                finding_ids=[], profile_version=0, created_at=now(), updated_at=now(),
                graph_group_id=graph_group_id, funding_status='not_researched',
                funding_summary='', research_profile={'claims': []}, enrichment_status='pending')
            candidate.setdefault('funding_status', 'not_researched')
            candidate.setdefault('funding_summary', '')
            candidate.setdefault('research_profile', {'claims': []})
            candidate.setdefault('enrichment_status', 'pending')
            candidate.setdefault('enrichment_profile_version', None)
            # A retry of a materialization does not bump versions or duplicate evidence.
            if finding['id'] in candidate['finding_ids']:
                ids.append(record_id)
                continue
            candidate['name'] = node['name']
            for key in ('description', 'website', 'location'):
                value = attrs.get(key) or (node.get('description') if key == 'description' else '')
                if isinstance(value, str) and value:
                    if key == 'website' and urlparse(value).scheme not in ('https', 'http'):
                        continue
                    if candidate.get(key) and candidate[key] != value:
                        candidate.setdefault('conflicts', []).append(dict(field=key,
                            previous=candidate[key], incoming=value, finding_id=finding['id']))
                    else:
                        candidate[key] = value
            people = attrs.get('people', [])
            if isinstance(people, list):
                candidate['people'] = sorted(set(candidate['people'] + [p for p in people if isinstance(p, str)]))
            country = str(attrs.get('country', '')).casefold()
            if country in ('de', 'germany', 'deutschland'):
                candidate['germany_status'] = 'likely'  # Extracted assertion, not independent confirmation.
            elif country:
                candidate['germany_status'] = 'outside_germany'
            quote = attrs.get('evidence_quote', '')
            if quote and quote not in finding['text']:
                raise ValueError('Evidence quote is absent from source')
            evidence_id = str(uuid5(NAMESPACE_URL, record_id+':'+finding['id']))
            store.put('evidence', dict(id=evidence_id, candidate_id=record_id,
                finding_id=finding['id'], episode_id=receipt['episode_id'], url=finding['url'],
                title=finding['title'], quote=quote or finding['text'][:2000],
                kind='exact_quote' if quote else 'source_excerpt',
                attribution='Source linked by extraction; excerpt is not proof of every profile field.',
                published_at=finding.get('published_at'), fetched_at=finding['fetched_at'],
                created_at=now()), c)
            # Graph facts retain their graph/episode provenance; no fabricated source quotations.
            for edge in receipt['edges']:
                if node['id'] not in (edge['source'], edge['target']):
                    continue
                signal_id = str(uuid5(NAMESPACE_URL, evidence_id+':'+edge['id']))
                candidate['signals'].append(dict(id=signal_id, kind='graph_fact', label=edge['fact'],
                    evidence_id=evidence_id, graph_edge_id=edge['id'], date=finding.get('published_at'),
                    verification='model_extracted'))
            candidate['signals'] = list({s['id']: s for s in candidate['signals']}.values())
            candidate['finding_ids'].append(finding['id'])
            candidate['profile_version'] += 1
            candidate['updated_at'] = now()
            source_id = finding.get('source_id') or finding.get('source') or ''
            if str(source_id).startswith('research:'):
                # A research-origin finding is already part of the current
                # enrichment pass; do not create a research → ingest → research loop.
                candidate['enrichment_profile_version'] = candidate['profile_version']
            candidate['open_questions'] = ['Bisherige Finanzierung überprüfen.', 'Zahlungsbereitschaft und Kundenbelege prüfen.']
            if candidate['germany_status'] != 'confirmed':
                candidate['open_questions'].append('Tatsächlichen oder geplanten Unternehmenssitz bestätigen.')
            store.put('candidates', candidate, c)
            store.event('candidate.updated' if previous else 'candidate.created', record_id,
                        {'finding_id': finding['id'], 'profile_version': candidate['profile_version']}, c)
            if legacy:
                for old_note in store.list('notes', c):
                    if old_note.get('candidate_id') != legacy['id']:
                        continue
                    migrated_id = str(uuid5(NAMESPACE_URL, f"{old_note['id']}:{record_id}"))
                    if not store.get('notes', migrated_id, c):
                        store.put('notes', dict(old_note, id=migrated_id, candidate_id=record_id,
                            migrated_from=legacy['id']), c)
            if enqueue_evaluation:
                store.enqueue('evaluate', {'id': record_id}, f"evaluate:{record_id}:{candidate['profile_version']}", c)
                if not str(source_id).startswith('research:'):
                    candidate['enrichment_status'] = 'queued'
                    candidate['enrichment_requested_profile_version'] = candidate['profile_version']
                    store.put('candidates', candidate, c)
                    store.enqueue('research', {'id': record_id,
                        'profile_version': candidate['profile_version']},
                        f"research:{record_id}:{candidate['profile_version']}", c)
            ids.append(record_id)
        if update_finding:
            current = app.require('findings', finding['id'], c)
            current.update(status='processed', candidate_ids=ids, updated_at=now())
            store.put('findings', current, c)
    return ids
