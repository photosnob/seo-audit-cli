"""robots.txt loading on top of the standard-library parser.

Crawl-delay is only honored when it is a whole number of seconds. That is a
limitation of urllib.robotparser, and the report says when a delay was applied.
"""

from dataclasses import dataclass
from urllib.robotparser import RobotFileParser


@dataclass(slots=True)
class Robots:
    status: int | None
    found: bool
    allow_all: bool
    unavailable: bool
    error: str | None
    text: str
    sitemaps: list[str]
    crawl_delay: float | None
    parser: RobotFileParser | None

    def allows(self, url: str, user_agent: str) -> bool:
        if self.allow_all or self.parser is None:
            return True
        return bool(self.parser.can_fetch(user_agent, url))


def parse_robots(text: str, robots_url: str, status: int = 200) -> Robots:
    parser = RobotFileParser(robots_url)
    parser.parse(text.splitlines())
    listed = parser.site_maps() or []
    sitemaps = [item.strip() for item in listed if item.strip()]
    return Robots(
        status=status,
        found=True,
        allow_all=False,
        unavailable=False,
        error=None,
        text=text,
        sitemaps=sitemaps,
        crawl_delay=None,
        parser=parser,
    )


def robots_allow_all(
    *,
    status: int | None,
    found: bool,
    unavailable: bool,
    error: str | None,
    text: str = "",
) -> Robots:
    return Robots(
        status=status,
        found=found,
        allow_all=True,
        unavailable=unavailable,
        error=error,
        text=text,
        sitemaps=[],
        crawl_delay=None,
        parser=None,
    )


def delay_for(robots: Robots, user_agent: str) -> float | None:
    if robots.parser is None:
        return None
    delay = robots.parser.crawl_delay(user_agent)
    if delay is None:
        return None
    return float(delay)
