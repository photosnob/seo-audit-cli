"""JSON and CSV exports."""

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from seoaudit.checks import iter_documents
from seoaudit.models import SEVERITIES, AuditReport, Page

LIMITATIONS = [
    "HTML is fetched as the server sent it. JavaScript is not executed.",
    "Visible word count includes navigation and excludes script, style, noscript, template, and svg.",
    "Page weight is the HTML document size, not the weight of images, CSS, or scripts.",
    "Image checks read src and data-src. Those image URLs are not downloaded.",
    "Open Graph image URLs are not downloaded.",
    "Sitemap URLs are requested even past --max-depth. Links found on them still obey the depth limit.",
    "With concurrency above 1, --max-depth follows the path that discovered each URL. Reported depth is the shortest path among crawled pages.",
    "Python's robots parser only honors Crawl-delay values that are whole seconds.",
    "A missing robots.txt is treated as no restrictions. A 4xx or 5xx robots.txt is also treated as no restrictions and is reported.",
    "External links are checked up to --max-external. Links past that cap are counted and not requested.",
]


def summarize(report: AuditReport) -> dict[str, Any]:
    documents = iter_documents(report.pages)
    indexable = [page for page in documents if page.indexable()]
    by_severity = dict.fromkeys(SEVERITIES, 0)
    by_code: dict[str, int] = {}
    for issue in report.issues:
        by_severity[issue.severity] += 1
        by_code[issue.code] = by_code.get(issue.code, 0) + 1
    return {
        "pages": len(report.pages),
        "documents": len(documents),
        "indexable": len(indexable),
        "issues": len(report.issues),
        "by_severity": by_severity,
        "by_code": by_code,
        "external_checked": len(report.external),
        "external_considered": report.external_considered,
        "blocked": len(report.blocked_urls),
        "sitemap_urls": len(report.sitemap_urls),
        "requests": report.requests_made,
    }


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    return {
        "tool": "seoaudit",
        "version": report.version,
        "report_schema": 1,
        "start_url": report.start_url,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_seconds": report.duration_seconds,
        "score": report.score.overall,
        "score_by_category": report.score.categories,
        "deductions": [asdict(item) for item in report.score.deductions],
        "settings": report.settings,
        "limitations": LIMITATIONS,
        "robots": {
            "status": report.robots_status,
            "found": report.robots_found,
            "unavailable": report.robots_unavailable,
            "error": report.robots_error,
            "sitemaps": report.robots_sitemaps,
            "crawl_delay": report.crawl_delay,
            "text": report.robots_text,
        },
        "sitemap": {
            "sources": report.sitemap_sources,
            "urls": report.sitemap_urls,
            "errors": report.sitemap_errors,
            "truncated": report.sitemap_truncated,
        },
        "summary": summarize(report),
        "issues": [asdict(issue) for issue in report.issues],
        "pages": [_page_dict(page) for page in report.pages],
        "external_checks": [asdict(item) for item in report.external],
        "external_considered": report.external_considered,
        "blocked_urls": report.blocked_urls,
        "requests_made": report.requests_made,
    }


def render_json(report: AuditReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, ensure_ascii=False) + "\n"


def write_report(report: AuditReport, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    from seoaudit.html_report import render_html

    paths = {
        "html": output_dir / "report.html",
        "json": output_dir / "report.json",
        "issues": output_dir / "issues.csv",
        "pages": output_dir / "pages.csv",
    }
    paths["html"].write_text(render_html(report), encoding="utf-8")
    paths["json"].write_text(render_json(report), encoding="utf-8")
    _write_issues(paths["issues"], report)
    _write_pages(paths["pages"], report)
    return paths


def _page_dict(page: Page) -> dict[str, Any]:
    data = asdict(page)
    data["indexable"] = page.indexable()
    return data


def _write_issues(path: Path, report: AuditReport) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["severity", "code", "url", "message"])
        for issue in report.issues:
            writer.writerow([issue.severity, issue.code, issue.url, issue.message])


def _write_pages(path: Path, report: AuditReport) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "url",
                "final_url",
                "status",
                "depth",
                "indexable",
                "title",
                "meta_description",
                "h1",
                "canonical",
                "word_count",
                "html_bytes",
                "source",
                "elapsed_ms",
                "error",
            ]
        )
        for page in report.pages:
            writer.writerow(
                [
                    page.url,
                    page.final_url,
                    "" if page.status is None else page.status,
                    "" if page.depth is None else page.depth,
                    "yes" if page.indexable() else "no",
                    page.title or "",
                    page.meta_description or "",
                    " | ".join(page.h1s),
                    " | ".join(page.canonicals),
                    page.word_count,
                    page.html_bytes,
                    page.source,
                    page.elapsed_ms,
                    page.error or "",
                ]
            )
