"""Default on-page thresholds.

These are the usual search-snippet and content heuristics this tool applies.
They are not ranking factors published by a search engine. Every report records
the values it used.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Thresholds:
    title_min: int = 30
    title_max: int = 60
    meta_min: int = 70
    meta_max: int = 160
    thin_words: int = 300
    very_thin_words: int = 50
    html_large_bytes: int = 200_000
    html_very_large_bytes: int = 500_000
    # Shortest internal click path. The start document is depth 0.
    deep_depth: int = 4
