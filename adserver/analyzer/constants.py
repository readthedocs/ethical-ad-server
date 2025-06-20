"""Contants used for the ad server keyword/topic analyzer."""

# Query parameters on URLs to ignore
IGNORED_QUERY_PARAMS = (
    "q",
    "query",
    "search",
    "utm_campaign",
    "utm_medium",
    "utm_source",
    "utm_label",
    "utm_keyword",
    "utm_content",
    "utm_term",
    "utm_id",
    "ref",
)

ANALYZER_REANALYZE_DATE_THRESHOLD = 90  # days
ANALYZER_MIN_VISITS = 100  # visits
