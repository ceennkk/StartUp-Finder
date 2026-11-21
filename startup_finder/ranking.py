"""Deterministic, explainable sourcing score derived from evidence-backed ratings."""

CRITERIA_VERSION = 'sourcing-rank-v5'
FUNDING_CLASSIFICATION_VERSION = 'funding-nature-v1'
RATING_POINTS = {'strong': 100, 'moderate': 67, 'weak': 33}
MIN_SCORED_CRITERIA = 3
EQUITY_CONFIRMED_SCORE = 0


def score_assessment(assessment, funding_status=None, funding_type=None,
                     equity_assessment=None, eligibility_assessment=None):
    """Add an equal-weight score; unknown criteria stay out of the mean.

    A score is withheld unless at least three of four criteria have evidence-backed
    non-unknown ratings. This prevents sparse profiles from looking rankable.
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
    criteria_score = round(sum(rated) / count) if count >= MIN_SCORED_CRITERIA else None
    score = criteria_score
    equity_status = (equity_assessment or {}).get('status')
    eligibility_status = (eligibility_assessment or {}).get('htgf_eligibility_status')
    eligibility_effect = 'eligibility_unverified'
    funding_effect = 'insufficient_criteria' if score is None else 'no_verified_equity_effect'
    funding_adjustment = None if score is None else 0
    if eligibility_status == 'htgf_not_eligible':
        # Confirmed hard-gate failure outranks the sourcing score, including
        # candidates with too little evidence to compute the regular score.
        score = 0
        eligibility_effect = 'requirements_not_met'
        funding_effect = 'eligibility_gate_failed'
    elif eligibility_status == 'pre_company_candidate':
        score = None
        eligibility_effect = 'company_not_registered'
    elif eligibility_status == 'htgf_eligible':
        eligibility_effect = 'requirements_met'
    else:
        score = None
        eligibility_effect = 'eligibility_unverified'
    # Research labels and source quotes can surface a possible funding event,
    # but only a separate, human-reviewed external-equity assessment changes
    # the score. Grants and unknown financing are never treated as equity.
    if score is not None and eligibility_status == 'htgf_eligible' and equity_status == 'equity_confirmed':
        score = EQUITY_CONFIRMED_SCORE
        funding_effect = 'equity_confirmed_zero_score'
        funding_adjustment = score - criteria_score
    elif score is not None and equity_status == 'no_public_equity_round_found':
        funding_effect = 'reviewed_no_public_equity_round_found'
    elif score is not None and equity_status == 'equity_status_unclear':
        funding_effect = 'equity_status_unclear_no_penalty'
    if score is None:
        priority = 'insufficient_data'
    elif score >= 75:
        priority = 'high'
    elif score >= 50:
        priority = 'medium'
    else:
        priority = 'low'
    assessment.update(score=score, criteria_score=criteria_score,
        scored_criteria=count, priority=priority,
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
