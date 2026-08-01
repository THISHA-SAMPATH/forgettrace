import asyncio
import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from forgettrace.audit import build_report, verify_report
from forgettrace.datahub_client import DataHubMCPClient
from forgettrace.remediation import generate_tasks
from forgettrace.traversal import find_direct_matches, walk_downstream

console = Console()


@click.group()
def main():
    """ForgetTrace — an agent for provable data erasure."""


@main.command()
@click.option("--subject-column", required=True, help="Identifier column, e.g. patient_id")
@click.option("--subject-value", required=True, help="The specific subject's value, e.g. P10432")
@click.option("--max-hops", default=6, show_default=True)
@click.option("--output", default=None, help="Path to write the signed JSON report")
def trace(subject_column: str, subject_value: str, max_hops: int, output: str | None):
    """Find every dataset (direct + downstream) containing a subject's data
    and generate a signed compliance audit report."""
    asyncio.run(_trace(subject_column, subject_value, max_hops, output))


async def _trace(subject_column: str, subject_value: str, max_hops: int, output: str | None):
    client = DataHubMCPClient()
    async with client.connect():
        console.print(f"[bold]Searching DataHub for datasets containing[/bold] {subject_column}...")
        root_urns = await find_direct_matches(client, subject_column, subject_value)
        console.print(f"Found {len(root_urns)} direct match(es). Walking downstream lineage...")

        nodes, issues = await walk_downstream(client, root_urns, max_hops=max_hops)
        tasks = generate_tasks(nodes, issues)
        report = build_report(subject_column, subject_value, nodes, issues, remediation_tasks=tasks)

    _render_table(nodes)
    if issues:
        console.print(f"\n[yellow]{len(issues)} issue(s) flagged for manual review[/yellow]")
    if tasks:
        console.print(f"[cyan]{len(tasks)} remediation task(s) generated[/cyan]")
        for t in tasks:
            console.print(f"  [{t['priority']}] {t['task_id']} — {t['urn']} — {t['action']}")

    out_path = Path(output) if output else Path(f"reports/{report['request_id']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    console.print(f"\n[green]Signed audit report written to {out_path}[/green]")
    console.print(f"Signature: {report['signature']}")


@main.command()
@click.argument("report_path")
def verify(report_path: str):
    """Verify a previously generated report hasn't been tampered with."""
    report = json.loads(Path(report_path).read_text())
    if verify_report(report):
        console.print("[green]Valid — report has not been modified since generation.[/green]")
    else:
        console.print("[red]INVALID — report contents do not match its signature.[/red]")


def _render_table(nodes):
    table = Table(title="Datasets Affected")
    table.add_column("URN")
    table.add_column("Platform")
    table.add_column("Hops")
    table.add_column("Confidence")
    for n in nodes:
        table.add_row(n.urn, n.platform, str(n.hops), n.confidence)
    console.print(table)


if __name__ == "__main__":
    main()
