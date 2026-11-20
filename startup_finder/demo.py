"""Offline fixtures, not actual startup leads or AI outputs."""
from .store import now

TEAMS = [
    dict(key='robot', name='DemoRobot', kind='StartupVenture', location='Aachen',
         description='Fiktiver Roboterprototyp für die Inspektion von Produktionsanlagen.',
         website='https://example.org/demorobot', country='DE', people=['Anna Beispiel', 'Max Muster'],
         evidence_quote='Anna Beispiel und Max Muster planen die Gründung von DemoRobot in Aachen, Deutschland. Ein Roboterprototyp wird getestet. Das Team sucht Pilotkunden.',
         signals=['founding_intent', 'prototype', 'germany_location']),
    dict(key='bio', name='DemoBio', kind='StartupVenture', location='Darmstadt',
         description='Fiktives Forschungsprojekt zur Zellbildanalyse.',
         website='https://example.org/demobio', country='', people=['Alex Demo'],
         evidence_quote='Alex Demo entwickelt DemoBio an einer Hochschule in Darmstadt. Gründungsabsicht und Unternehmenssitz sind noch nicht bestätigt.',
         signals=[]),
    dict(key='energy', name='DemoEnergy', kind='StartupVenture', location='München',
         description='Fiktive Software zur Planung industrieller Energienutzung.',
         website='https://example.org/demoenergy', country='DE', people=['Sam Beispiel'],
         evidence_quote='Sam Beispiel plant die Gründung von DemoEnergy in München, Deutschland. Ein Prototyp liegt vor. Ein Industriepartner äußert Interesse an einem Pilotprojekt; ein Vertrag ist nicht bestätigt.',
         signals=['founding_intent', 'prototype', 'germany_location', 'pilot_interest']),
]


def seed(app):
    if app.settings.mode != 'demo':
        raise ValueError('Demo seed disabled in live mode')
    app.store.put('sources', dict(id='demo-source', name='Synthetisches Gründungszentrum',
        url='https://example.org/demo', kind='manual', allowed_hosts=['example.org'], enabled=True,
        is_demo=True, created_at=now(), updated_at=now()))
    jobs = []
    for team in TEAMS:
        finding = app.import_finding(dict(source_id='demo-source', external_id=team['key'],
            url=team['website'], title=f"DEMO: {team['name']}",
            text='SYNTHETISCH – KEIN REALER LEAD.\n'+team['evidence_quote']))
        finding.update(is_demo=True, demo_entities=[team])
        app.store.put('findings', finding)
        jobs.append(app.queue('process', finding['id']))
    return dict(is_demo=True, jobs=jobs, message='Synthetische Fundstellen importiert; Worker verarbeitet sie.')
