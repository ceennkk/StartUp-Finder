"""Materialize candidate profiles from resolved graph nodes and their provenance."""
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5
from .store import now


def materialize(app, finding, receipt):
    store = app.store
    ids = []
    with store.transaction() as c:
        for node in receipt['nodes']:
            existing_node = store.get('graph_nodes', node['id'], c) or {}
            store.put('graph_nodes', dict(existing_node, **node), c)
        for edge in receipt['edges']:
            old = store.get('graph_edges', edge['id'], c) or {}
            edge = dict(edge, episode_ids=sorted(set(old.get('episode_ids', []) + edge.get('episode_ids', []))))
            store.put('graph_edges', edge, c)
        for node in receipt['nodes']:
            if 'StartupVenture' not in node.get('labels', []):
                continue
            attrs = node.get('attributes') or node
            record_id = node['id']
            previous = store.get('candidates', record_id, c)
            candidate = previous or dict(id=record_id, graph_node_id=node['id'], name=node['name'],
                description='', website='', location='', germany_status='unknown', entity_type='venture',
                people=[], signals=[], open_questions=[], status='new', is_demo=finding['is_demo'],
                finding_ids=[], profile_version=0, created_at=now(), updated_at=now())
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
            quote = attrs.get('evidence_quote', '') if finding['is_demo'] else ''
            if quote and quote not in finding['text']:
                raise ValueError('Evidence quote is absent from source')
            evidence_id = str(uuid5(NAMESPACE_URL, record_id+':'+finding['id']))
            store.put('evidence', dict(id=evidence_id, candidate_id=record_id,
                finding_id=finding['id'], episode_id=receipt['episode_id'], url=finding['url'],
                title=finding['title'], quote=quote or finding['text'][:2000],
                kind='exact_quote' if quote else 'source_excerpt',
                attribution='Source linked by extraction; excerpt is not proof of every profile field.',
                published_at=finding.get('published_at'), fetched_at=finding['fetched_at'],
                is_demo=finding['is_demo'], created_at=now()), c)
            signal_labels = dict(founding_intent='Gründungsabsicht', prototype='Prototyp',
                                 germany_location='Standortangabe Deutschland', pilot_interest='Pilotinteresse')
            for signal in attrs.get('signals', []) if finding['is_demo'] else []:
                signal_id = str(uuid5(NAMESPACE_URL, evidence_id+':'+signal))
                candidate['signals'].append(dict(id=signal_id, kind=signal, label=signal_labels.get(signal, signal),
                    evidence_id=evidence_id, date=finding.get('published_at'), is_demo=True))
            # Live facts retain their graph/episode provenance; no fabricated source quotations.
            for edge in receipt['edges'] if not finding['is_demo'] else []:
                if node['id'] not in (edge['source'], edge['target']):
                    continue
                signal_id = str(uuid5(NAMESPACE_URL, evidence_id+':'+edge['id']))
                candidate['signals'].append(dict(id=signal_id, kind='graph_fact', label=edge['fact'],
                    evidence_id=evidence_id, graph_edge_id=edge['id'], date=finding.get('published_at'),
                    is_demo=False, verification='model_extracted'))
            candidate['signals'] = list({s['id']: s for s in candidate['signals']}.values())
            candidate['finding_ids'].append(finding['id'])
            candidate['profile_version'] += 1
            candidate['updated_at'] = now()
            candidate['open_questions'] = ['Bisherige Finanzierung überprüfen.', 'Zahlungsbereitschaft und Kundenbelege prüfen.']
            if candidate['germany_status'] != 'confirmed':
                candidate['open_questions'].append('Tatsächlichen oder geplanten Unternehmenssitz bestätigen.')
            store.put('candidates', candidate, c)
            store.event('candidate.updated' if previous else 'candidate.created', record_id,
                        {'finding_id': finding['id'], 'profile_version': candidate['profile_version']}, c)
            store.enqueue('evaluate', {'id': record_id}, f"evaluate:{record_id}:{candidate['profile_version']}", c)
            ids.append(record_id)
        current = app.require('findings', finding['id'], c)
        current.update(status='processed', candidate_ids=ids, updated_at=now())
        store.put('findings', current, c)
    return ids
