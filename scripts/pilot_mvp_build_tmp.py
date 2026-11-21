from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.connection import make_engine
from app.database.models import Entity, EntityAlias, EntitySourceRecord, Observation, Relationship, Signal, Source, SourceRecord
from app.database.repositories import IngestionRepository
from app.domain import AliasType, EntityType, RelationshipType, RunStatus, SourceType
from app.evidence.identifiers import stable_id
from app.evidence.models import Claim, ClaimExtraction, ClaimKind, Document, Evidence, Source as FinanceSource
from app.evidence.validation import validate_claim_extraction
from app.finance.assessment import assess_equity
from app.finance.models import (
    AmountQualifier, EquityFinding, EquityStage, EquityStatus, EventScope, EventStatus,
    FinancialSupportEvent, Provenance, SupportCategory, TriState,
)
from app.ingestion.types import AliasDraft, EntityDraft, NormalizedBundle, RawRecord, RelationshipDraft, SourceSpec
from app.utils.hashing import content_hash

ROOT = Path(r"O:\Hackathon\StartUp-Finder")
OUT = [
    ROOT / "data" / "exports" / "pilot_finance.json",
    ROOT / "data" / "exports" / "knowledge_graph_pilot.json",
    ROOT / "docs" / "knowledge-graph-handoff.md",
]
if any(path.exists() for path in OUT):
    raise FileExistsError("Refusing to overwrite an existing pilot deliverable")
TODAY = date.today()
RETRIEVED = TODAY.isoformat()

COMPANIES = {
    "onsite": ("OnSite Solutions GmbH", "organization:onsite-solutions",
               "Digital building-operations company developing the BAIOSS platform.", "https://onsite-solutions.eu/"),
    "nodeline": ("nodeline GmbH", "organization:nodeline",
                 "Company developing AI-assisted data integration products.", "https://nodeline.de/"),
    "floronics": ("Floronics", "organization:floronics",
                  "Official site describes a pre-launch European deep-tech startup building photosynthesis-imaging technology; legal form not verified.",
                  "https://floronics.eu/"),
    "deepset": ("deepset GmbH", "organization:deepset",
                "Berlin-based company building enterprise AI software and the Haystack framework.", "https://www.deepset.ai/"),
}


def draft(key, identifier, kind, name, description=None, website=None, properties=None):
    aliases = [AliasDraft(alias=website, alias_type=AliasType.URL)] if website else []
    return EntityDraft(key=key, identifier=identifier, entity_type=kind, canonical_name=name,
                       description=description, properties=properties or {}, aliases=aliases,
                       is_primary=True, extraction_method="curated_public_source")


def company(slug):
    name, identifier, description, website = COMPANIES[slug]
    props = {"pilot_case": "mvp_pilot_2026_11", "website": website}
    props["identity_source_type"] = "official_company_site" if slug == "floronics" else "official_company_imprint"
    return draft(slug, identifier, EntityType.ORGANIZATION, name, description, website, props)


def tech(key, name, description):
    return draft(key, f"technology:{key}", EntityType.TECHNOLOGY, name, description,
                 properties={"pilot_case": "mvp_pilot_2026_11"})


def program(key, name, description):
    return draft(key, f"program:{key}", EntityType.FUNDING_PROGRAM, name, description,
                 properties={"pilot_case": "mvp_pilot_2026_11"})


REC = [
    dict(key="onsite_article", url="https://www.kit-forge.de/de/magazin/grundung-des-monats-onsite-solutions/",
         title="Gründung des Monats: OnSite Solutions", publisher="KIT-FORGE",
         type="university_incubator_article", date="2026-09-23",
         quotes=[
             "Mit BAIOSS entwickeln wir eine Plattform, die Gebäudeeigentümer, Betreiber und Planer hilft, den digitalen Reifegrad eines Gebäudes zu verstehen und daraus konkrete Maßnahmen abzuleiten.",
             "Die Idee ist aus unserer gemeinsamen Arbeit am KIT entstanden.",
             "Unterstützung durch die KIT-Gründerschmiede",
             "Wir befinden uns aktuell noch in der Förderung durch das EXIST Gründerstipendium.",
         ], entities=[company("onsite"), tech("baioss", "BAIOSS", "Platform for assessing and improving the digital readiness of buildings.")],
         rels=[("onsite", "baioss", RelationshipType.DEVELOPED, {"relationship_context": "company describes BAIOSS as its platform"})]),
    dict(key="onsite_imprint", url="https://onsite-solutions.eu/impressum/", title="Impressum",
         publisher="OnSite Solutions GmbH", type="official_company_imprint", date=None,
         quotes=["OnSite Solutions GmbH", "Sitz: Karlsruhe · Registergericht: Amtsgericht Mannheim · HRB 758315"],
         entities=[company("onsite")], rels=[]),
    dict(key="nodeline_article", url="https://www.kit-forge.de/de/magazin/grndung-des-monats-nodeline/",
         title="Gründung des Monats: nodeline", publisher="KIT-FORGE",
         type="university_incubator_article", date="2026-08-21",
         quotes=[
             "Wir entwickeln KI-gestützte Software, die fachliche Anforderungen in technische Datenprozesse übersetzt.",
             "Mit der ersten Ausprägung von flowAI beginnen wir",
             "Förderantrag im Programm StartupSecure eingereicht. Aktuell warten wir noch auf den Förderbescheid.",
         ], entities=[company("nodeline"), tech("flowai", "flowAI", "AI-assisted product for translating business requirements into technical data processes.")],
         rels=[("nodeline", "flowai", RelationshipType.DEVELOPED, {"relationship_context": "KIT-FORGE profile identifies flowAI as the first product implementation"})]),
    dict(key="nodeline_home", url="https://nodeline.de/", title="nodeline", publisher="nodeline GmbH",
         type="official_company_site", date=None,
         quotes=["nodeline ist ein deutscher Hersteller KI-gestützter Integrationslösungen."],
         entities=[company("nodeline")], rels=[]),
    dict(key="nodeline_imprint", url="https://nodeline.de/impressum/", title="Impressum",
         publisher="nodeline GmbH", type="official_company_imprint", date=None,
         quotes=["nodeline GmbH", "Amtsgericht Mannheim HRB 754387"],
         entities=[company("nodeline")], rels=[]),
    dict(key="startupsecure_program", url="https://www.kit-forge.de/de/netzwerk/startup-secure-kastel/",
         title="Startup Secure Kastel", publisher="KIT-FORGE", type="official_program_page", date=None,
         quotes=["StartupSecure KASTEL ist der KIT-Inkubator für Startups im Bereich IT-Sicherheit"],
         entities=[program("startupsecure-kastel", "StartupSecure KASTEL", "KIT incubator and program context for IT-security startups.")],
         rels=[]),
    dict(key="floronics_home", url="https://floronics.eu/", title="Floronics - See what others can’t",
         publisher="Floronics", type="official_company_site", date=None,
         quotes=["The first field-deployable camera for real-time photosynthesis imaging under natural sunlight.",
                 "European deep-tech · Pre-launch"],
         entities=[company("floronics"), tech("sifcam", "SIFcam", "Field-deployable camera for solar-induced fluorescence and photosynthesis imaging.")],
         rels=[("floronics", "sifcam", RelationshipType.DEVELOPED, {"relationship_context": "official site presents SIFcam as its product"})]),
    dict(key="floronics_about", url="https://floronics.eu/about", title="About us | Floronics",
         publisher="Floronics", type="official_company_site", date=None,
         quotes=["Floronics is a young European deep-tech start-up, straight out of research.",
                 "We build a drone camera for sun-induced fluorescence"],
         entities=[company("floronics")], rels=[]),
    dict(key="future_greentech_program", url="https://www.futureforest.de/en/future-greentech-incubator",
         title="Future Greentech Incubator", publisher="Future Forest Initiative", type="official_program_page", date=None,
         quotes=["Future GreenTech Incubator offers up to €300,000 non-dilutive funding for selected startups."],
         entities=[program("future-greentech-incubator", "Future GreenTech Incubator",
                           "Incubation program offering selected startups up to €300,000 non-dilutive funding.")], rels=[]),
    dict(key="deepset_imprint", url="https://www.deepset.ai/imprint", title="Imprint",
         publisher="deepset GmbH", type="official_company_imprint", date="2024-08-09",
         quotes=["deepset GmbH", "10115 Berlin, Germany", "Handelsregister: HRB 197429 B"],
         entities=[company("deepset")], rels=[]),
    dict(key="deepset_techcrunch",
         url="https://techcrunch.com/2023/08/09/deepset-secures-30m-to-expand-its-llm-focused-mlops-offerings/",
         title="Deepset secures $30M to expand its LLM-focused MLOps offerings", publisher="TechCrunch",
         type="independent_media", date="2023-08-09",
         quotes=["it raised $30 million in a funding round led by Balderton Capital with participation from GV and Harpoon Ventures.",
                 "released Haystack, an open source framework to build NLP back-end services"],
         entities=[company("deepset"), tech("haystack", "Haystack", "Open-source framework for building NLP back-end services.")],
         rels=[("deepset", "haystack", RelationshipType.DEVELOPED, {"relationship_context": "TechCrunch reports deepset released Haystack"})]),
]

settings = get_settings()
direct = urlsplit(settings.database_url_direct)
if not direct.hostname or not direct.hostname.endswith(".neon.tech") or direct.path.lstrip("/") != "neondb":
    raise RuntimeError("Direct target did not match the authorized Neon database")
engine = make_engine(url=settings.database_url_direct)
now = datetime.now(timezone.utc)
source_name = "manual_pilot_research"
source_record_ids = {}

with Session(engine) as session:
    with session.begin():
        revision = session.execute(text("select version_num from public.alembic_version")).scalar_one()
        if revision != "0001":
            raise RuntimeError(f"Unexpected database revision: {revision}")
        source_existing = session.execute(select(Source).where(Source.source_name == source_name)).scalar_one_or_none()
        if source_existing is None:
            names = [entry[0] for entry in COMPANIES.values()]
            collisions = session.execute(select(EntityAlias.alias).where(
                EntityAlias.alias_type == AliasType.NAME.value, EntityAlias.alias.in_(names)
            )).scalars().all()
            if collisions:
                raise RuntimeError(f"Pilot-name collision guard failed: {collisions!r}")
        repo = IngestionRepository(session)
        source = repo.ensure_source(SourceSpec(
            source_name=source_name, source_type=SourceType.MANUAL,
            description="One-off curated pilot research records with short public-source excerpts; not an automated collector.",
        ))
        run = repo.start_run(source.id, now, {"mode": "curated_public_source_load", "pilot_cases": list(COMPANIES)})
        created = updated = unchanged = 0
        for item in REC:
            payload = {"title": item["title"], "publisher": item["publisher"], "source_type": item["type"],
                       "published_on": item["date"], "retrieved_on": RETRIEVED,
                       "evidence": [{"field": "public_source_excerpt", "quote": quote} for quote in item["quotes"]]}
            stored = repo.upsert_source_record(source.id, run.id,
                RawRecord(external_id=item["url"], record_type="pilot_evidence", payload=payload, canonical_url=item["url"]), now)
            created += stored.status == "created"
            updated += stored.status == "updated"
            unchanged += stored.status == "unchanged"
            rels = [RelationshipDraft(source_key=a, target_key=b, relationship_type=typ, properties=props)
                    for a, b, typ, props in item["rels"]]
            repo.store_bundle(source.id, stored.record, NormalizedBundle(entities=item["entities"], relationships=rels),
                              now, settings.observation_bucket)
            source_record_ids[item["key"]] = str(stored.record.id)
        repo.finish_run(run, status=RunStatus.SUCCESS, completed_at=datetime.now(timezone.utc),
                        fetched=len(REC), created=created, updated=updated, failed=0, error_message=None,
                        metadata={"records_unchanged": unchanged, "manual_source_reviewed": True})
        company_ids = {}
        for slug, (_, identifier, _, _) in COMPANIES.items():
            company_ids[slug] = str(session.execute(
                select(Entity.id).join(EntityAlias, EntityAlias.entity_id == Entity.id).where(
                    EntityAlias.source_id == source.id, EntityAlias.alias_type == AliasType.SOURCE_IDENTIFIER.value,
                    EntityAlias.external_identifier == identifier,
                )).scalar_one())
        run_id, source_id = str(run.id), str(source.id)


def provenance(candidate_id, record_keys, claim_type, kind, statement, uncertainties):
    sources, documents, evidence, evidence_ids, refs = [], [], [], [], []
    with Session(engine) as session:
        for key in record_keys:
            item = next(row for row in REC if row["key"] == key)
            db_record = session.execute(select(SourceRecord).where(
                SourceRecord.id == source_record_ids[key])).scalar_one()
            payload = db_record.raw_payload
            sid = stable_id("source", {"url": item["url"]})
            if sid not in {source.source_id for source in sources}:
                sources.append(FinanceSource(source_id=sid, title=payload["title"], url=item["url"],
                    publisher=payload["publisher"], source_type=payload["source_type"]))
            fields = {"excerpts": [row["quote"] for row in payload["evidence"]]}
            digest = content_hash(fields)
            did = stable_id("document", {"source_id": sid, "content_hash": digest})
            documents.append(Document(document_id=did, source_id=sid, content_hash=digest,
                published_on=date.fromisoformat(payload["published_on"]) if payload["published_on"] else None,
                retrieved_on=date.fromisoformat(payload["retrieved_on"]), fields=fields))
            refs.append(source_record_ids[key])
            for quote in fields["excerpts"]:
                eid = stable_id("evidence", {"document_id": did, "field_path": "excerpts", "quote": quote})
                evidence.append(Evidence(evidence_id=eid, document_id=did, field_path="excerpts", quote=quote))
                evidence_ids.append(eid)
    identity = {"candidate_id": candidate_id, "claim_type": claim_type, "kind": kind.value,
                "statement": statement, "evidence_ids": sorted(evidence_ids)}
    claim = Claim(claim_id=stable_id("claim", identity), candidate_id=candidate_id, claim_type=claim_type,
                  kind=kind, statement=statement, evidence_ids=evidence_ids, uncertainties=uncertainties)
    extraction = ClaimExtraction(claims=[claim], evidence=evidence)
    validate_claim_extraction(extraction, documents)
    return Provenance(sources=sources, documents=documents, extraction=extraction), refs


EVENTS, FINDINGS, ASSESSMENTS, EVENT_REFS = [], [], {}, {}
event_specs = {
    "onsite": (["onsite_article"], "The KIT-FORGE interview reports that the team is currently supported through the EXIST-Gründerstipendium; it does not identify a company award amount or legal recipient."),
    "nodeline": (["nodeline_article", "startupsecure_program"], "The KIT-FORGE interview reports a StartupSecure grant application awaiting decision; no award, contract, payment, or amount is reported."),
    "floronics": (["future_greentech_program"], "The program offers selected startups up to EUR 300,000 in non-dilutive funding; this does not establish that Floronics applied, was selected, or received funds."),
    "deepset": (["deepset_techcrunch"], "TechCrunch reported that deepset raised USD 30 million in a funding round led by Balderton Capital with GV and Harpoon Ventures participating; instrument and equity terms are not specified."),
}
uncertainties = {
    "onsite": ["Award recipients and legal recipient are not specified; the source describes founder-team support, not company equity.", "The source does not disclose an amount."],
    "nodeline": ["The application was pending; no grant award, contract, payment, or amount was reported.", "A grant application is not evidence of equity financing."],
    "floronics": ["The offer applies to selected startups; no company-specific application or selection evidence was located.", "The brief's approximate EUR 300,000 initial-funding claim was not corroborated; no receipt is recorded.", "The legal form GmbH i.G. was not verified from an official legal notice."],
    "deepset": ["The report does not specify financing instrument, share terms, or completion details.", "No human review is recorded; equity status remains unclear."],
}
for slug, (keys, statement) in event_specs.items():
    cid = company_ids[slug]
    prov, refs = provenance(cid, keys, "support", ClaimKind.FACT_CANDIDATE, statement, uncertainties[slug])
    common = dict(event_id=stable_id("support_event", {"candidate_id": cid, "source_records": refs, "slug": slug}),
                  candidate_id=cid, provenance=prov, uncertainties=uncertainties[slug])
    if slug == "onsite":
        event = FinancialSupportEvent(**common, category=SupportCategory.FOUNDER_STIPEND,
            scope=EventScope.PROGRAM_PARTICIPATION, applicant="OnSite founding team",
            beneficiary="Founding team; individual recipients not identified", funder="EXIST-Gründerstipendium",
            program_or_project="EXIST-Gründerstipendium", statuses=(EventStatus.UNKNOWN,))
    elif slug == "nodeline":
        event = FinancialSupportEvent(**common, category=SupportCategory.PUBLIC_GRANT, scope=EventScope.INDIVIDUAL,
            applicant="nodeline GmbH", funder="BMFTR (StartUpSecure program context)",
            program_or_project="StartupSecure grant application; decision pending in the 2026-08-21 KIT-FORGE interview",
            statuses=(EventStatus.APPLIED,))
    elif slug == "floronics":
        event = FinancialSupportEvent(**common, category=SupportCategory.PUBLIC_GRANT, scope=EventScope.PROGRAM_OFFER,
            funder="Future GreenTech Incubator", amount=Decimal("300000"), currency="EUR",
            amount_qualifier=AmountQualifier.UP_TO, program_or_project="Future GreenTech Incubator public offer",
            statuses=(EventStatus.UNKNOWN,), repayable=TriState.UNKNOWN, dilutive=TriState.NO)
    else:
        event = FinancialSupportEvent(**common, category=SupportCategory.VENTURE_CAPITAL, scope=EventScope.INDIVIDUAL,
            beneficiary="deepset GmbH", funder="Balderton Capital; GV; Harpoon Ventures",
            amount=Decimal("30000000"), currency="USD", amount_qualifier=AmountQualifier.EXACT,
            program_or_project="Funding round reported in 2023; round stage not specified in the retrieved report",
            statuses=(EventStatus.ANNOUNCED,))
    EVENTS.append(event)
    EVENT_REFS[event.event_id] = refs
    if slug == "deepset":
        eq_prov, eq_refs = provenance(cid, ["deepset_techcrunch"], "external_equity", ClaimKind.HYPOTHESIS,
            "The reported USD 30 million funding round may represent external equity; confirm instrument and closing terms through human review.",
            ["The source does not provide equity-instrument or share-allocation details.", "No human review or primary issuer/investor confirmation is recorded."])
        finding = EquityFinding(finding_id=stable_id("equity_finding", {"candidate_id": cid, "source_records": eq_refs}),
            candidate_id=cid, stage=EquityStage.UNCLEAR, provenance=eq_prov)
        FINDINGS.append(finding)
        ASSESSMENTS[slug] = assess_equity(cid, TODAY, [finding], [event])
    else:
        ASSESSMENTS[slug] = assess_equity(cid, TODAY, [], [event])
if any(item.status != EquityStatus.EQUITY_STATUS_UNCLEAR for item in ASSESSMENTS.values()):
    raise RuntimeError("Unexpected equity status; no human-reviewed finding or complete search coverage exists")

with Session(engine) as session:
    src = session.execute(select(Source).where(Source.id == source_id)).scalar_one()
    sr = session.execute(select(SourceRecord).where(SourceRecord.source_id == src.id).order_by(SourceRecord.external_id)).scalars().all()
    sr_ids = [record.id for record in sr]
    entity_links = session.execute(select(EntitySourceRecord).where(EntitySourceRecord.source_record_id.in_(sr_ids))).scalars().all()
    rels = session.execute(select(Relationship).where(Relationship.source_record_id.in_(sr_ids))).scalars().all()
    sigs = session.execute(select(Signal).where(Signal.source_record_id.in_(sr_ids))).scalars().all()
    obs = session.execute(select(Observation).where(Observation.source_record_id.in_(sr_ids))).scalars().all()
    entity_ids = {row.entity_id for row in entity_links} | {r.source_entity_id for r in rels} | {r.target_entity_id for r in rels}
    entities = session.execute(select(Entity).where(Entity.id.in_(entity_ids))).scalars().all()
    linked_by_entity = {}
    for row in entity_links:
        linked_by_entity.setdefault(str(row.entity_id), []).append(str(row.source_record_id))
    url_by_record = {str(record.id): record.canonical_url for record in sr}
    graph = {
        "schema_version": "1.0", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_revision": "0001", "scope": "manual_pilot_research source; source-scoped entities only",
        "identity_note": "Entities are source-scoped; matching names across sources are not merged.",
        "entities": [{"id": str(e.id), "entity_type": e.entity_type, "canonical_name": e.canonical_name,
            "description": e.description, "properties": e.properties,
            "source_record_ids": sorted(linked_by_entity.get(str(e.id), []))}
            for e in sorted(entities, key=lambda x: (x.entity_type, x.canonical_name.lower()))],
        "relationships": [{"id": str(r.id), "source_entity_id": str(r.source_entity_id),
            "target_entity_id": str(r.target_entity_id), "relationship_type": r.relationship_type,
            "verification_status": r.verification_status, "confidence": str(r.confidence) if r.confidence is not None else None,
            "properties": r.properties, "source_record_id": str(r.source_record_id),
            "source_url": url_by_record.get(str(r.source_record_id))} for r in rels],
        "signals": [{"id": str(s.id), "entity_id": str(s.entity_id), "signal_type": s.signal_type,
            "description": s.signal_description, "event_date": s.event_date.isoformat() if s.event_date else None,
            "published_at": s.published_at.isoformat() if s.published_at else None,
            "properties": s.properties, "source_record_id": str(s.source_record_id)} for s in sigs],
        "observations": [{"id": str(o.id), "entity_id": str(o.entity_id), "metric_name": o.metric_name,
            "value": str(o.metric_value), "unit": o.metric_unit, "observed_at": o.observed_at.isoformat(),
            "source_record_id": str(o.source_record_id), "metadata": o.metadata} for o in obs],
        "source_records": [{"id": str(r.id), "source_name": source_name, "external_id": r.external_id,
            "record_type": r.record_type, "canonical_url": r.canonical_url,
            "published_at": r.published_at.isoformat() if r.published_at else None, "raw_payload": r.raw_payload,
            "entity_ids": sorted(str(link.entity_id) for link in entity_links if link.source_record_id == r.id)} for r in sr],
        "pilot_company_entity_ids": company_ids,
        "counts": {"entities": len(entities), "relationships": len(rels), "signals": len(sigs),
                   "observations": len(obs), "source_records": len(sr)},
    }

    identity_keys = {"onsite": ["onsite_imprint"], "nodeline": ["nodeline_imprint"],
                     "floronics": ["floronics_home", "floronics_about"], "deepset": ["deepset_imprint"]}
    notes = {
        "onsite": ["Official imprint confirms OnSite Solutions GmbH in Karlsruhe.", "EXIST support is reported for the founding team, not as company equity; amount and legal recipient are not specified."],
        "nodeline": ["Official imprint confirms nodeline GmbH.", "The StartupSecure application was pending; the previously circulated EUR 798,682 is not recorded as an awarded nodeline grant."],
        "floronics": ["Official site describes Floronics as pre-launch and identifies SIFcam; legal form was not verified.", "The EUR 300,000 figure is a general selected-startup program offer, not a company-specific receipt.", "No independent evidence of Floronics selection or participation in the Future GreenTech Incubator was located."],
        "deepset": ["Official imprint confirms deepset GmbH in Berlin.", "TechCrunch reports a USD 30 million funding round in 2023; instrument and equity status remain unverified without human review.", "No pre-first-round classification is present or assigned."],
    }
    finance = {
        "schema_version": "1.0", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "assessment_as_of": TODAY.isoformat(), "database_revision": "0001",
        "candidate_id_semantics": "Finance candidate_id equals the actual pilot company Entity UUID; no Candidate table exists.",
        "companies": [{"entity_id": company_ids[slug], "canonical_name": COMPANIES[slug][0],
            "identity_source_record_ids": [source_record_ids[key] for key in identity_keys[slug]],
            "events": [e.model_dump(mode="json") for e in EVENTS if e.candidate_id == company_ids[slug]],
            "event_source_record_ids": {e.event_id: EVENT_REFS[e.event_id] for e in EVENTS if e.candidate_id == company_ids[slug]},
            "equity_findings": [f.model_dump(mode="json") for f in FINDINGS if f.candidate_id == company_ids[slug]],
            "equity_assessment": ASSESSMENTS[slug].model_dump(mode="json"),
            "identity_and_finance_notes": notes[slug]} for slug in COMPANIES],
        "source_record_ids_by_key": source_record_ids,
        "equity_policy_note": "Grants and program offers are not equity. No reviewer identity was supplied, so none of the four assessments is equity_confirmed or no_public_equity_round_found.",
    }

(ROOT / "data" / "exports").mkdir(parents=True, exist_ok=True)
OUT[0].write_text(json.dumps(finance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
OUT[1].write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
with Session(engine) as verify_session:
    counts = {name: verify_session.execute(text(f"select count(*) from public.{name}")).scalar_one()
              for name in ["source_records", "entities", "entity_aliases", "entity_source_records", "relationships", "signals", "observations", "ingestion_runs"]}
print(json.dumps({"status": "committed", "target_host": direct.hostname, "database": direct.path.lstrip("/"),
    "revision": "0001", "source_name": source_name, "source_id": source_id, "ingestion_run_id": run_id,
    "records_fetched": len(REC), "records_created": created, "records_updated": updated, "records_unchanged": unchanged,
    "pilot_company_entity_ids": company_ids, "source_record_ids": source_record_ids, "postwrite_counts": counts,
    "graph_counts": graph["counts"], "equity_assessments": {k: v.status.value for k, v in ASSESSMENTS.items()},
    "written_exports": [str(path) for path in OUT[:2]]}, ensure_ascii=False, indent=2))
engine.dispose()
