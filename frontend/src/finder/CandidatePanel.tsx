"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useApi, useLoad } from "./hooks";
import type { Candidate, CandidateDetail, CandidateStatus, Evidence, Graph } from "./types";
import { ErrorBox, Loading, fmtDate, fmtTime } from "./ui";
import { useLanguage } from "./i18n";

function EvidenceRefs({ ids, evidence }: { ids: (string | null | undefined)[]; evidence: Evidence[] }) {
  const { language, t } = useLanguage();
  const [open, setOpen] = useState<string | null>(null);
  const clean = ids.filter((id): id is string => !!id);
  if (!clean.length) return null;
  return <span className="fa-refs">
    {clean.map((id) => {
      const index = evidence.findIndex((item) => item.id === id);
      const item = evidence[index];
      if (!item) return null;
      return <span key={id} className="fa-ref">
        <button className={`fa-ref__btn${open === id ? " is-on" : ""}`} onClick={() => setOpen(open === id ? null : id)} aria-expanded={open === id} aria-label={t("evidence", { number: index + 1 })}>{index + 1}</button>
        {open === id && <span className="fa-ref__pop" role="dialog" aria-label={t("evidence", { number: index + 1 })}>
          <span className="fa-ref__src">{item.title ?? t("sourcesUsed")} · {item.published_at ? fmtDate(item.published_at, language) : fmtDate(item.fetched_at, language)}</span>
          <q>{item.quote}</q>
          {item.url && <a href={item.url} target="_blank" rel="noreferrer">{t("openOriginal")}</a>}
        </span>}
      </span>;
    })}
  </span>;
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="fa-profile__row"><span>{label}</span><div>{children}</div></div>;
}

function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean).filter((word) => !/^(inc\.?|ltd\.?|gmbh|ag|se|the)$/i.test(word));
  return (words.length > 1 ? words.slice(0, 2).map((word) => word[0]) : [(words[0] ?? name)[0], (words[0] ?? name)[1]]).join("").toUpperCase();
}

function faviconFor(website: string) {
  try {
    const url = new URL(website);
    if (url.protocol === "http:" || url.protocol === "https:") return new URL("/favicon.ico", url.origin).toString();
  } catch { /* show the monogram if the website is unavailable */ }
  return null;
}

export function CandidatePanel({ id, preview, onChanged, onClose }: { id: string; preview: Candidate; onChanged: () => void; onClose: () => void }) {
  const { language, t } = useLanguage();
  const { api, toast } = useApi();
  const { data: candidate, error, loading, reload, setData } = useLoad((client) => client.getCandidate(id), [id]);
  const { data: graph } = useLoad((client) => client.graph(), [id]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [logoFailed, setLogoFailed] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  if (loading && !candidate) return <article className="fa-cand fa-profile fa-profile--loading">
    <header className="fa-cand__head"><div className="fa-cand__top">
      <span className="fa-profile__brandmark" aria-hidden="true">{preview.website && !logoFailed ? <img src={faviconFor(preview.website) ?? undefined} alt="" onError={() => setLogoFailed(true)} /> : initials(preview.name)}</span>
      <div className="fa-profile__identity"><p className="fa-meta">{preview.entity_type?.replaceAll("_", " ") || t("companyDetails")}</p><h2>{preview.name}</h2></div>
      <button className="fa-close" onClick={onClose} aria-label={t("closeProfile")}>×</button>
    </div></header>
    <div className="fa-profile__preview-content">
      {preview.description && <p>{preview.description}</p>}
      {preview.assessment_rankable && typeof preview.assessment?.score === "number" && <span className="fa-profile__score">{preview.assessment.score}<small>/100</small></span>}
      <Loading label={t("loadingCandidateDetails")} />
    </div>
  </article>;
  if (error && !candidate) return <article className="fa-cand fa-profile fa-profile--loading">
    <header className="fa-cand__head"><div className="fa-cand__top"><div className="fa-profile__identity"><p className="fa-meta">{t("companyDetails")}</p><h2>{preview.name}</h2></div><button className="fa-close" onClick={onClose} aria-label={t("closeProfile")}>×</button></div></header>
    <div className="fa-profile__preview-content"><ErrorBox message={error} onRetry={reload} /></div>
  </article>;
  if (!candidate) return null;

  const assessment = candidate.assessment_current && typeof candidate.assessment?.score === "number" ? candidate.assessment : null;
  const eligibilityResult = candidate.eligibility?.assessment_result;
  const eligibilityStatus = candidate.assessment?.eligibility_effect;
  const eligibilityRows = eligibilityResult ? [
    { key: "germany", status: eligibilityResult.germany_presence_status, detail: eligibilityResult.criteria.germany },
    { key: "technology", status: eligibilityResult.technology_status, detail: eligibilityResult.criteria.technology },
    { key: "age", status: eligibilityResult.company_age_status, detail: eligibilityResult.criteria.company_age },
  ] : null;
  const contentDates = [assessment?.created_at, ...candidate.evidence.map((item) => item.fetched_at), ...candidate.research_runs.map((item) => item.created_at)]
    .filter((date): date is string => !!date).sort();
  const dataAsOf = contentDates.at(-1);
  const claims = candidate.research_profile?.claims ?? [];
  const favicon = candidate.website ? faviconFor(candidate.website) : null;
  const claimsFor = (...fields: string[]) => claims.filter((claim) => fields.includes(claim.field) && claim.value?.trim());
  const fundingClaims = claimsFor("funding", "funding_round");
  const reportedGrantClaims = fundingClaims.filter((claim) => claim.funding_nature === "non_dilutive");
  const otherFundingClaims = fundingClaims.filter((claim) => claim.funding_nature !== "non_dilutive");
  const reviewedSupportEvents = (candidate.finance?.events ?? []).filter((event) =>
    event.dilutive === "no" && ["public_grant", "founder_stipend", "research_funding", "prize", "in_kind_support"].includes(event.category));
  const equityStatus = candidate.finance?.equity_assessment?.status ?? assessment?.equity_status;
  const showFinance = Boolean(candidate.finance || fundingClaims.length || (candidate.funding_status && candidate.funding_status !== "not_researched" && candidate.funding_status !== "not_found"));
  const visibleSignals = candidate.signals.filter((signal) => signal.kind !== "funding");
  const displayLocation = candidate.location.split(";")[0].trim();
  const people = candidate.people.filter((person) => person.length <= 60 && !/^(the company|founders listed|founding team)/i.test(person));
  const rawNeighbors = (graph?.edges ?? []).flatMap((edge) => {
    const isSource = edge.source === candidate.graph_node_id;
    const isTarget = edge.target === candidate.graph_node_id;
    if (!isSource && !isTarget) return [];
    const otherId = isSource ? edge.target : edge.source;
    const node = graph?.nodes.find((item) => item.id === otherId);
    return node ? [{ node, edge, direction: isSource ? "outgoing" : "incoming" as const }] : [];
  });
  const neighborGroups = new Map<string, { node: Graph["nodes"][number]; direction: "incoming" | "outgoing"; relations: { relation: string; fact: string }[] }>();
  for (const item of rawNeighbors) {
    const group = neighborGroups.get(item.node.id) ?? { node: item.node, direction: item.direction as "incoming" | "outgoing", relations: [] };
    const relation = item.edge.relation.replaceAll("_", " ");
    if (!group.relations.some((entry) => entry.relation === relation && entry.fact === (item.edge.fact ?? ""))) {
      group.relations.push({ relation, fact: item.edge.fact ?? "" });
    }
    neighborGroups.set(item.node.id, group);
  }
  const neighborGroupsSorted = [...neighborGroups.values()].sort((a, b) => {
    const rank = (item: typeof a) => item.node.labels?.some((label) => /person|investor|accelerator|organization/i.test(label)) ? 0 : 1;
    return rank(a) - rank(b) || a.node.name.localeCompare(b.node.name);
  });
  const visibleNeighbors = neighborGroupsSorted.slice(0, 6);
  const moreNeighbors = neighborGroupsSorted.slice(6, 18);

  const setStatus = async (status: CandidateStatus) => {
    setBusy(true);
    try {
      const updated = await api.patchCandidate(candidate.id, { status });
      setData({ ...candidate, status: updated.status, updated_at: updated.updated_at } as CandidateDetail);
      toast(status === "shortlisted" ? t("shortlistAdded") : status === "rejected" ? t("candidateHidden") : t("candidateRestored"));
      onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : t("saveFailed"), "error");
    } finally {
      setBusy(false);
    }
  };

  const saveNote = async () => {
    if (!note.trim()) return;
    setBusy(true);
    try {
      const saved = await api.addNote(candidate.id, note);
      setData({ ...candidate, notes: [saved, ...candidate.notes] });
      setNote("");
      toast(t("noteSaved"));
    } catch (e) {
      toast(e instanceof Error ? e.message : t("noteNotSaved"), "error");
    } finally {
      setBusy(false);
    }
  };

  return <article className="fa-cand fa-cand--compact fa-profile">
    <header className="fa-cand__head">
      <div className="fa-cand__top">
        <span className="fa-profile__brandmark" aria-hidden="true">{favicon && !logoFailed ? <img src={favicon} alt="" onError={() => setLogoFailed(true)} /> : initials(candidate.name)}</span>
        <div className="fa-profile__identity">
          <p className="fa-meta">{candidate.entity_type?.replaceAll("_", " ") || t("companyDetails")}</p>
          <h2>{candidate.name}</h2>
        </div>
        <button className="fa-close" onClick={onClose} aria-label={t("closeProfile")}>×</button>
      </div>
      <div className="fa-cand__actions">
        <button className={`htgf-btn${candidate.status === "shortlisted" ? " htgf-btn--outline" : ""}`} disabled={busy} onClick={() => setStatus(candidate.status === "shortlisted" ? "new" : "shortlisted")}>
          {candidate.status === "shortlisted" ? t("saved") : t("shortlistAction")}
        </button>
        <button className="fa-link" disabled={busy} onClick={() => setStatus(candidate.status === "rejected" ? "new" : "rejected")}>
          {candidate.status === "rejected" ? t("restoreCandidate") : t("hideCandidate")}
        </button>
      </div>
      {dataAsOf && <p className="fa-cand__updated">{t("updated", { date: fmtTime(dataAsOf, language) })}</p>}
    </header>

    <section className="fa-profile__section fa-profile__overview">
      <h3>{t("overview")}</h3>
      {(candidate.description || claimsFor("description")[0]?.value) && <p className="fa-profile__description">{candidate.description || claimsFor("description")[0]?.value}</p>}
      <div className="fa-profile__fields">
        {displayLocation && <InfoRow label={t("location")}>{displayLocation}</InfoRow>}
        {candidate.website && <InfoRow label={t("website")}><a href={candidate.website} target="_blank" rel="noreferrer">{candidate.website} ↗</a></InfoRow>}
        {claimsFor("founded_year").map((claim, index) => <InfoRow key={`founded:${index}`} label={t("founded")}>{claim.value.match(/\b(?:19|20)\d{2}\b/)?.[0] ?? claim.value}</InfoRow>)}
      </div>
    </section>

    <section className="fa-profile__section fa-cand__section-team" aria-label={t("teamAndOrganization")}>
      <h3>{t("teamAndOrganization")}</h3>
      {people.length > 0 && <InfoRow label={t("team")}><div className="fa-profile__chips">{people.map((person) => <span key={person}>{person}</span>)}</div></InfoRow>}
      {claimsFor("team").length > 0 && <details className="fa-profile__details"><summary>{t("teamDetails")}</summary>{claimsFor("team").map((claim, index) => <p key={`team:${index}`}>{claim.value} <EvidenceRefs ids={[claim.evidence_id]} evidence={candidate.evidence} /></p>)}</details>}
      {people.length === 0 && claimsFor("team").length === 0 && <p className="fa-profile__empty">{t("noVerifiedDetails")}</p>}
    </section>

    {visibleNeighbors.length > 0 && <section className="fa-profile__section fa-profile__network" aria-label={t("connectedEntities")}>
      <h3>{t("connectedEntities")}</h3>
      <div className="fa-profile__relations">{visibleNeighbors.map(({ node, relations, direction }) => <article className="fa-profile__relation" key={node.id}>
        <span className="fa-profile__relation-type">{node.labels?.map((label) => label.replaceAll(/([a-z])([A-Z])/g, "$1 $2")).join(" · ")}</span>
        <b>{node.name}</b>
        <div className="fa-profile__relation-tags">{relations.slice(0, 2).map((item, index) => <span key={`${item.relation}:${index}`}>{item.relation} {direction === "outgoing" ? "→" : "←"}</span>)}</div>
        {relations.some((item) => item.fact) && <details className="fa-profile__relation-evidence"><summary>{t("relationshipDetails")}</summary>{relations.slice(0, 2).filter((item) => item.fact).map((item, index) => <p key={`${item.relation}:${index}`}>{item.fact}</p>)}</details>}
      </article>)}</div>
      {moreNeighbors.length > 0 && <details className="fa-profile__details fa-profile__more-links">
        <summary>{t("moreConnections", { count: moreNeighbors.length })}</summary>
        <div className="fa-profile__relations">{moreNeighbors.map(({ node, relations, direction }) => <article className="fa-profile__relation" key={node.id}>
          <span className="fa-profile__relation-type">{node.labels?.map((label) => label.replaceAll(/([a-z])([A-Z])/g, "$1 $2")).join(" · ")}</span>
          <b>{node.name}</b>
          <div className="fa-profile__relation-tags">{relations.slice(0, 2).map((item, index) => <span key={`${item.relation}:${index}`}>{item.relation} {direction === "outgoing" ? "→" : "←"}</span>)}</div>
          {relations.some((item) => item.fact) && <details className="fa-profile__relation-evidence"><summary>{t("relationshipDetails")}</summary>{relations.slice(0, 2).filter((item) => item.fact).map((item, index) => <p key={`${item.relation}:${index}`}>{item.fact}</p>)}</details>}
        </article>)}</div>
        {neighborGroupsSorted.length > 18 && <small className="fa-profile__links-note">{t("additionalConnections", { count: neighborGroupsSorted.length - 18 })}</small>}
      </details>}
    </section>}

    {(claimsFor("product", "technology", "market", "traction").length > 0) && <section className="fa-profile__section fa-profile__product">
      <h3>{t("productAndMarket")}</h3>
      <div className="fa-profile__fields">{claimsFor("product", "technology", "market", "traction").map((claim, index) => <InfoRow key={`${claim.field}:${index}`} label={t(`field_${claim.field}` as "field_product" | "field_technology" | "field_market" | "field_traction")}>{claim.value} <EvidenceRefs ids={[claim.evidence_id]} evidence={candidate.evidence} /></InfoRow>)}</div>
    </section>}

    <section className="fa-profile__section fa-profile__eligibility">
      <h3>{t("eligibility")}</h3>
      <p className="fa-profile__finance-note">{t("eligibilityRequirements")}</p>
      {eligibilityStatus === "requirements_not_met" && <p className="fa-profile__empty">{t("eligibilityNotMet")}</p>}
      {eligibilityStatus === "company_not_registered" && <p className="fa-profile__empty">{t("eligibilityPreCompany")}</p>}
      {eligibilityStatus === "eligibility_unverified" && <p className="fa-profile__empty">{t("eligibilityReviewNeeded")}</p>}
      {eligibilityRows && eligibilityResult ? <div className="fa-profile__fields">{eligibilityRows.map(({ key, status, detail }) => <InfoRow key={key} label={t(key === "germany" ? "germanyCriterion" : key === "technology" ? "technologyCriterion" : "ageCriterion")}>
        <span>{status === "satisfied" || status === "within_three_years" || status === "registered_seat_in_germany" || status === "relocation_to_germany_planned" || status === "german_permanent_establishment_planned" ? t("criteriaSatisfied") : status === "not_satisfied" || status === "older_than_three_years" || status === "no_germany_connection" ? t("criteriaNotSatisfied") : status === "not_registered" ? t("ageNotRegistered") : t("criteriaUnclear")}</span>
        {key === "technology" && eligibilityResult.technology_fields.length > 0 && <small className="fa-profile__finance-caveat">{t("sectorFields", { fields: eligibilityResult.technology_fields.join(", ") })}</small>}
        {detail.evidence.length > 0 && <details className="fa-profile__details"><summary>{t("showEligibilityEvidence")}</summary>{detail.evidence.map((item, index) => <p key={`${item.url}:${index}`}><a href={item.url} target="_blank" rel="noreferrer">{item.title} ↗</a><small className="fa-profile__finance-caveat">{item.publisher} · {item.claim}</small></p>)}</details>}
      </InfoRow>)}</div> : <p className="fa-profile__empty">{t("eligibilityNoAssessment")}</p>}
    </section>

    {showFinance && <section className="fa-profile__section fa-profile__funding">
      <h3>{t("financingEvidence")}</h3>
      <p className="fa-profile__finance-note">{t("financingIsContext")}</p>
      {equityStatus === "equity_confirmed" && <InfoRow label={t("equityReview")}><b>{t(candidate.assessment_current ? (typeof candidate.assessment?.score === "number" ? "equityCapApplied" : "equityCapNoScore") : "equityCapPending")}</b></InfoRow>}
      {equityStatus === "equity_status_unclear" && <InfoRow label={t("equityReview")}>{t("equityUnclearNoPenalty")}</InfoRow>}
      {equityStatus === "no_public_equity_round_found" && <InfoRow label={t("equityReview")}>{t("noPublicEquityFound", { date: candidate.finance?.as_of ?? "" })}</InfoRow>}
      {reviewedSupportEvents.map((event) => <InfoRow key={event.event_id} label={t("nonDilutiveSupport")}>
        {event.program_or_project || event.funder || t("supportAward")}
        {event.amount && event.currency ? ` · ${event.amount} ${event.currency}` : ""}
      </InfoRow>)}
      {reportedGrantClaims.slice(0, 2).map((claim, index) => <InfoRow key={`grant:${index}`} label={t("reportedSupport")}>
        <span>{claim.value}<small className="fa-profile__finance-caveat">{t("researchNotReviewed")}</small></span>
        <EvidenceRefs ids={[claim.evidence_id]} evidence={candidate.evidence} />
      </InfoRow>)}
      {otherFundingClaims.slice(0, 2).map((claim, index) => <InfoRow key={`funding:${index}`} label={t("fundingNotClassified")}>
        <span>{claim.value}<small className="fa-profile__finance-caveat">{t("researchNotReviewed")}</small></span>
        <EvidenceRefs ids={[claim.evidence_id]} evidence={candidate.evidence} />
      </InfoRow>)}
      {fundingClaims.length > 4 && <details className="fa-profile__details"><summary>{t("moreFundingDetails", { count: fundingClaims.length - 4 })}</summary>{fundingClaims.slice(4).map((claim, index) => <p key={`funding-extra:${index}`}>{claim.value} <EvidenceRefs ids={[claim.evidence_id]} evidence={candidate.evidence} /></p>)}</details>}
      {!equityStatus && !reviewedSupportEvents.length && !fundingClaims.length && candidate.funding_summary && <InfoRow label={t("fundingNotClassified")}><span>{candidate.funding_summary}<small className="fa-profile__finance-caveat">{t("researchNotReviewed")}</small></span></InfoRow>}
    </section>}

    <section className="fa-profile__section fa-cand__rank" aria-label={t("assessment")}>
      <div className="fa-profile__section-heading"><h3>{t("assessment")}</h3>{assessment ? <span className="fa-profile__score">{assessment.score}<small>/100</small></span> : <span className="fa-profile__pending">{t("scorePending")}</span>}</div>
      {assessment && <>
      <p className="fa-cand__summary">{assessment.summary} <EvidenceRefs ids={assessment.evidence_ids} evidence={candidate.evidence} /></p>
      {assessment.score_provisional && <small className="fa-profile__finance-caveat">{t("provisionalScoreNote", { count: assessment.scored_criteria ?? 0 })}</small>}
      {(assessment.funding_effect === "confirmed_dilutive_funding_zero_score" || assessment.funding_effect === "equity_confirmed_zero_score") && <small className="fa-profile__finance-caveat">{t("dilutiveFundingPenalty")}</small>}
      <details className="fa-profile__details">
        <summary>{t("whyScore")}</summary>
        <div className="fa-cand__criteria">
          {assessment.criteria.map((criterion) => <div className="fa-cand__criterion" key={criterion.key}>
            <div><b>{criterion.label}</b><span>{t(`rating${criterion.rating[0].toUpperCase()}${criterion.rating.slice(1)}` as "ratingStrong" | "ratingModerate" | "ratingWeak" | "ratingUnknown")}</span></div>
            <p>{criterion.rationale} <EvidenceRefs ids={criterion.evidence_ids} evidence={candidate.evidence} /></p>
          </div>)}
        </div>
        {assessment.strengths.length > 0 && <p><b>{t("strengths")}:</b> {assessment.strengths.join(" · ")}</p>}
        {assessment.concerns.length > 0 && <p><b>{t("risks")}:</b> {assessment.concerns.join(" · ")}</p>}
      </details>
      </>}
    </section>

    {visibleSignals.length > 0 && <details className="fa-profile__details fa-profile__signals-details"><summary>{t("signals")} · {visibleSignals.length}</summary><div className="fa-profile__signals">{visibleSignals.slice(0, 12).map((signal) => <article key={signal.id}><b>{signal.label}</b>{signal.date && <small>{fmtDate(signal.date, language)}</small>}<EvidenceRefs ids={[signal.evidence_id]} evidence={candidate.evidence} /></article>)}</div>{visibleSignals.length > 12 && <small className="fa-profile__links-note">{t("additionalSignals", { count: visibleSignals.length - 12 })}</small>}</details>}

    <details className="fa-profile__details fa-profile__sources">
      <summary>{t("sourceEvidence")} · {candidate.evidence.length}</summary>
      <div className="fa-profile__source-list">
        {candidate.evidence.map((item, index) => <article key={item.id}>
          <div><b>{item.title ?? `${t("sourcesUsed")} ${index + 1}`}</b><small>{item.published_at ? fmtDate(item.published_at, language) : fmtDate(item.fetched_at, language)}</small></div>
          {item.quote && <q>{item.quote}</q>}
          {item.url && <a href={item.url} target="_blank" rel="noreferrer">{t("openOriginal")}</a>}
        </article>)}
      </div>
    </details>

    <details className="fa-profile__details fa-cand__more--notes">
      <summary>{t("notes")}{candidate.notes.length ? ` · ${candidate.notes.length}` : ""}</summary>
      <div className="fa-cand__notes">
        <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder={t("addNote")} aria-label={t("addNote")} rows={2} />
        <button className="htgf-btn htgf-btn--small" disabled={!note.trim() || busy} onClick={saveNote}>{t("save")}</button>
        {candidate.notes.map((item) => <p key={item.id}>{item.text}<small>{fmtTime(item.created_at, language)}</small></p>)}
      </div>
    </details>
  </article>;
}
