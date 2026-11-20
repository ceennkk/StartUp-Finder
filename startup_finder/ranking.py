"""Deterministic, explainable sourcing score derived from evidence-backed ratings."""

CRITERIA_VERSION = 'sourcing-rank-v1'
RATING_POINTS = {'strong': 100, 'moderate': 67, 'weak': 33}
MIN_SCORED_CRITERIA = 3


def score_assessment(assessment):
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
    score = round(sum(rated) / count) if count >= MIN_SCORED_CRITERIA else None
    if score is None:
        priority = 'insufficient_data'
    elif score >= 75:
        priority = 'high'
    elif score >= 50:
        priority = 'medium'
    else:
        priority = 'low'
    assessment.update(score=score, scored_criteria=count, priority=priority)
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
