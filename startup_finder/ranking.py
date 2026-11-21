"""Deterministic, explainable sourcing score derived from evidence-backed ratings."""

CRITERIA_VERSION = 'sourcing-rank-v7'
FUNDING_CLASSIFICATION_VERSION = 'funding-nature-v1'
RATING_POINTS = {'strong': 100, 'moderate': 67, 'weak': 33}
EQUITY_CONFIRMED_SCORE = 0
UNKNOWN_CRITERION_PRIOR = 50


def score_assessment(assessment, funding_status=None, funding_type=None,
                     equity_assessment=None, eligibility_assessment=None):
    """Add a 0–100 score even when evidence is incomplete.

    Unknown criteria receive a neutral prior of 50. Evidence coverage and
    confidence are exposed separately so a provisional score is never mistaken
    for a fully reviewed ranking. Confirmed exclusion and external equity score 0.
    """
    criteria = assessment.get('criteria', [])
    keys = [criterion.get('key') for criterion in criteria]
    expected = {'founding_intent', 'technical_substance', 'customer_problem', 'demand'}
    if len(criteria) != len(expected) or set(keys) != expected:
        raise ValueError('Assessment must contain exactly the four sourcing criteria')

    rated = []
    for criterion in criteria:
        rating = criterion.get('rating')
        citations = criterion.get('evidence_ids', [])
        if rating not in (*RATING_POINTS, 'unknown'):
            raise ValueError('Invalid criterion rating')
        if rating == 'unknown':
            continue
        if not citations:
            raise ValueError('Scored criteria require evidence references')
        rated.append(RATING_POINTS[rating])

    count = len(rated)
    criteria_score = round(sum(rated) / count) if count else None
    score = round((sum(rated) + (len(expected) - count) * UNKNOWN_CRITERION_PRIOR) / len(expected))
    equity_status = (equity_assessment or {}).get('status')
    eligibility_status = (eligibility_assessment or {}).get('htgf_eligibility_status')
    eligibility_effect = 'eligibility_unverified'
    funding_effect = 'no_verified_equity_effect'
    funding_adjustment = 0
    if eligibility_status == 'htgf_not_eligible':
        # Confirmed hard-gate failure outranks the sourcing score.
        score = 0
        eligibility_effect = 'requirements_not_met'
        funding_effect = 'eligibility_gate_failed'
    elif eligibility_status == 'pre_company_candidate':
        eligibility_effect = 'company_not_registered'
    elif eligibility_status == 'htgf_eligible':
        eligibility_effect = 'requirements_met'
    else:
        eligibility_effect = 'eligibility_unverified'
    # Research labels and source quotes can surface a possible funding event,
    # but only a separate, human-reviewed external-equity assessment changes
    # the score. Grants and unknown financing are never treated as equity.
    confirmed_dilutive_funding = (funding_status == 'confirmed'
                                  and funding_type in ('dilutive', 'mixed'))
    if equity_status == 'equity_confirmed':
        score = EQUITY_CONFIRMED_SCORE
        funding_effect = 'equity_confirmed_zero_score'
        funding_adjustment = score - (criteria_score if criteria_score is not None else UNKNOWN_CRITERION_PRIOR)
    elif confirmed_dilutive_funding:
        # Quote-verified research may identify an explicit private equity/VC
        # round even before a separate human-curated finance snapshot exists.
        score = EQUITY_CONFIRMED_SCORE
        funding_effect = 'confirmed_dilutive_funding_zero_score'
        funding_adjustment = score - (criteria_score if criteria_score is not None else UNKNOWN_CRITERION_PRIOR)
    elif equity_status == 'no_public_equity_round_found':
        funding_effect = 'reviewed_no_public_equity_round_found'
    elif equity_status == 'equity_status_unclear':
        funding_effect = 'equity_status_unclear_no_penalty'
    if score >= 75:
        priority = 'high'
    elif score >= 50:
        priority = 'medium'
    else:
        priority = 'low'
    confidence = ('high' if count == len(expected) and eligibility_status == 'htgf_eligible'
                  else 'medium' if count >= 3 else 'low')
    assessment.update(score=score, criteria_score=criteria_score,
        scored_criteria=count, score_confidence=confidence,
        score_provisional=(confidence != 'high'), priority=priority,
        funding_status=funding_status, funding_type=funding_type,
        equity_status=equity_status, eligibility_status=eligibility_status,
        eligibility_effect=eligibility_effect,
        funding_adjustment=funding_adjustment, funding_effect=funding_effect)
    return assessment


def is_current_rank(assessment, profile_version, current_profile_version):
    return bool(assessment and assessment.get('criteria_version') == CRITERIA_VERSION
                and isinstance(assessment.get('score'), int)
                and not isinstance(assessment.get('score'), bool)
                and assessment.get('score') is not None
                and profile_version == current_profile_version)


def is_current_assessment(assessment, current_profile_version):
    return bool(assessment and assessment.get('criteria_version') == CRITERIA_VERSION
                and assessment.get('profile_version') == current_profile_version)
