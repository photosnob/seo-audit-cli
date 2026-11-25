"""Severity-weighted triage score.

The score starts at 100. Each distinct issue code contributes:

    points = weight(severity) * (min(count, 5) + 1) / 2

Weights are critical 15, high 8, medium 3, low 1, and info 0. The fifth
occurrence of a code is the last one that adds points, so a template fault
cannot by itself drive the score through the floor more than three times its
weight. Info findings stay in the report and do not change the number.

This is a way to sort a crawl. It is not a prediction of rankings.
"""

from collections import defaultdict

from seoaudit.catalog import CATEGORIES, require_check
from seoaudit.models import Deduction, Issue, Score
from seoaudit.thresholds import Thresholds

WEIGHTS: dict[str, float] = {
    "critical": 15.0,
    "high": 8.0,
    "medium": 3.0,
    "low": 1.0,
    "info": 0.0,
}
COUNT_CAP = 5


def score_issues(
    issues: list[Issue],
    *,
    has_pages: bool,
    thresholds: Thresholds | None = None,
) -> Score:
    active = thresholds or Thresholds()
    if not has_pages:
        return Score(None, [], dict.fromkeys(CATEGORIES))
    grouped: dict[tuple[str, str], int] = defaultdict(int)
    for issue in issues:
        if issue.severity == "info":
            continue
        grouped[(issue.code, issue.severity)] += 1
    deductions: list[Deduction] = []
    for (code, severity), count in grouped.items():
        check = require_check(code, active)
        points = WEIGHTS[severity] * (min(count, COUNT_CAP) + 1) / 2
        deductions.append(
            Deduction(
                code=code,
                severity=severity,
                category=check.category,
                count=count,
                points=round(points, 1),
            )
        )
    deductions.sort(key=lambda item: (-item.points, item.code, item.severity))
    overall = _clamp(sum(item.points for item in deductions))
    categories: dict[str, float | None] = {}
    for category in CATEGORIES:
        spent = sum(item.points for item in deductions if item.category == category)
        categories[category] = _clamp(spent)
    return Score(overall, deductions, categories)


def _clamp(spent: float) -> float:
    return round(max(0.0, 100.0 - spent), 1)
