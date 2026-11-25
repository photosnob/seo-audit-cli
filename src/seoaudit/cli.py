"""Command-line interface."""

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from seoaudit.crawler import ProgressCallback, run_audit
from seoaudit.models import DEFAULT_USER_AGENT, SEVERITIES, AuditConfig, AuditReport
from seoaudit.report import summarize, write_report
from seoaudit.version import __version__

_SEVERITY_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "dim",
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "crawl":
        return _crawl(args)
    parser.print_help()
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seoaudit",
        description="Crawl a site and write a technical SEO audit.",
    )
    parser.add_argument("--version", action="version", version=f"seoaudit {__version__}")
    sub = parser.add_subparsers(dest="command")
    crawl = sub.add_parser("crawl", help="Crawl a site and write a report")
    crawl.add_argument(
        "url", help="Page to start from. https:// is added if the scheme is missing."
    )
    crawl.add_argument(
        "--max-pages", type=int, default=100, help="Maximum pages to fetch (default 100)"
    )
    crawl.add_argument(
        "--max-depth", type=int, default=6, help="Maximum link depth from an entry URL (default 6)"
    )
    crawl.add_argument(
        "--rate-limit", type=float, default=2.0, help="Maximum requests per second (default 2)"
    )
    crawl.add_argument(
        "--concurrency", type=int, default=4, help="Maximum in-flight requests (default 4)"
    )
    crawl.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds")
    crawl.add_argument("--max-redirects", type=int, default=10)
    crawl.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    crawl.add_argument("--output-dir", type=Path, default=Path("seoaudit-report"))
    crawl.add_argument(
        "--max-external", type=int, default=50, help="External URLs to check (default 50)"
    )
    crawl.add_argument(
        "--check-external",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Request external links, canonicals, and hreflang targets (default on)",
    )
    crawl.add_argument(
        "--ignore-robots", action="store_true", help="Fetch URLs robots.txt disallows"
    )
    crawl.add_argument("--include-subdomains", action="store_true")
    crawl.add_argument(
        "--trust-env",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use HTTP(S)_PROXY from the environment (default on)",
    )
    crawl.add_argument(
        "--fail-on",
        choices=SEVERITIES,
        help="Exit 1 when an issue at this severity or worse is present",
    )
    crawl.add_argument("--quiet", action="store_true", help="Print the score and output paths only")
    crawl.epilog = (
        "Example: seoaudit crawl https://example.com --max-pages 500\n"
        "Only crawl a site you are allowed to audit. Defaults are 100 pages and 2 requests/second."
    )
    crawl.formatter_class = argparse.RawDescriptionHelpFormatter
    return parser


def _crawl(args: argparse.Namespace) -> int:
    console = Console(stderr=False)
    try:
        config = AuditConfig(
            start_url=args.url,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            rate_limit=args.rate_limit,
            concurrency=args.concurrency,
            timeout=args.timeout,
            max_redirects=args.max_redirects,
            user_agent=args.user_agent,
            check_external=args.check_external,
            max_external=args.max_external,
            respect_robots=not args.ignore_robots,
            include_subdomains=args.include_subdomains,
            trust_env=args.trust_env,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    try:
        report = asyncio.run(_run(config, console, quiet=args.quiet))
    except KeyboardInterrupt:
        console.print("Crawl interrupted.")
        return 130
    paths = write_report(report, args.output_dir)
    _print_summary(console, report, paths, quiet=args.quiet)
    if args.fail_on and _failed(report, args.fail_on):
        return 1
    return 0


async def _run(config: AuditConfig, console: Console, *, quiet: bool) -> AuditReport:
    progress_callback: ProgressCallback | None = None
    progress = None
    task = None
    if not quiet:
        from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

        progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
            transient=True,
        )
        progress.start()
        task = progress.add_task("Crawling", total=config.max_pages)

        def on_progress(done: int, scheduled: int, url: str) -> None:
            assert progress is not None and task is not None
            label = url if len(url) <= 72 else url[:69] + "..."
            progress.update(task, completed=done, total=max(scheduled, done), description=label)

        progress_callback = on_progress
    try:
        return await run_audit(config, progress_callback)
    finally:
        if progress is not None:
            progress.stop()


def _print_summary(
    console: Console, report: AuditReport, paths: dict[str, Path], *, quiet: bool
) -> None:
    summary = summarize(report)
    score = "n/a" if report.score.overall is None else f"{report.score.overall:.1f}"
    console.print(f"seoaudit {report.version}")
    console.print(f"Start URL: {report.start_url}")
    console.print(f"Pages fetched: {summary['pages']}")
    console.print(f"Score: {score} / 100")
    if quiet:
        _print_paths(console, paths)
        return
    table = Table(title="Issues", show_header=True, header_style="bold")
    table.add_column("Severity")
    table.add_column("Count", justify="right")
    for severity in SEVERITIES:
        table.add_row(
            severity, str(summary["by_severity"][severity]), style=_SEVERITY_STYLE[severity]
        )
    console.print(table)
    counts: dict[str, int] = summary["by_code"]
    if counts:
        top = Table(title="Top issue codes")
        top.add_column("Severity")
        top.add_column("Code")
        top.add_column("Count", justify="right")
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        severity_of = {issue.code: issue.severity for issue in report.issues}
        for code, count in ranked[:12]:
            severity = severity_of.get(code, "info")
            top.add_row(severity, code, str(count), style=_SEVERITY_STYLE.get(severity, ""))
        console.print(top)
    if summary["external_considered"] > summary["external_checked"]:
        skipped = summary["external_considered"] - summary["external_checked"]
        console.print(f"{skipped} external URL(s) were not checked because of --max-external.")
    _print_paths(console, paths)


def _print_paths(console: Console, paths: dict[str, Path]) -> None:
    console.print("Wrote:")
    for path in paths.values():
        console.print(f"  {path}")


def _failed(report: AuditReport, threshold: str) -> bool:
    limit = SEVERITIES.index(threshold)
    return any(SEVERITIES.index(issue.severity) <= limit for issue in report.issues)


def _console_main() -> None:
    sys.exit(main())


if __name__ == "__main__":
    _console_main()
