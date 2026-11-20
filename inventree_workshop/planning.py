"""Stock, incoming quantity and demand of a part, and what that suggests.

    left over = in stock + still to come from open build orders
                - still needed by build orders

When that is below the minimum stock of the part, the pages suggest making
more. Open workshop jobs count as "still to come", so a shortage is only ever
suggested once. Nothing is started automatically.
"""

from __future__ import annotations

from . import jobs, logic


def demand_codes(include_pending: bool) -> list:
    """Status codes of the build orders whose requirements count as demand."""
    from build.status_codes import BuildStatus

    codes = [BuildStatus.PRODUCTION.value]

    if include_pending:
        codes.append(BuildStatus.PENDING.value)

    return codes


def part_numbers(part, include_pending: bool = False) -> dict:
    """Stock, incoming quantity and demand of a part."""
    from build.models import Build, BuildLine
    from build.status_codes import BuildStatusGroups

    stock = float(part.get_stock_count(include_variants=False))

    incoming = 0.0
    incoming_jobs = 0.0

    for build in Build.objects.filter(part=part, status__in=BuildStatusGroups.ACTIVE_CODES):
        meta = jobs.job_meta(build)

        if meta is not None and jobs.is_finished(build, meta):
            # Closed by the plugin: the build order is about to complete
            continue

        outstanding = max(0.0, float(build.quantity) - float(build.completed))
        incoming += outstanding

        if meta is not None:
            incoming_jobs += outstanding

    demand = 0.0
    demand_builds = []

    lines = BuildLine.objects.filter(
        bom_item__sub_part=part, build__status__in=demand_codes(include_pending)
    ).select_related('build')

    for line in lines:
        build = line.build
        total = float(build.quantity)
        outstanding = max(0.0, total - float(build.completed))
        remaining = float(line.quantity) - float(line.consumed)

        # Outputs can be completed without their components being consumed:
        # never count more than the outputs still to build would need
        if total > 0:
            remaining = min(remaining, float(line.quantity) * outstanding / total)

        if remaining <= 0:
            continue

        demand += remaining
        demand_builds.append({
            'pk': build.pk,
            'reference': build.reference,
            'quantity': remaining,
        })

    return {
        'stock': stock,
        'incoming': incoming,
        'incoming_jobs': incoming_jobs,
        'demand': demand,
        'demand_builds': demand_builds,
        'minimum': float(part.minimum_stock or 0),
    }


def suggestion(link: dict, numbers: dict) -> dict:
    """Whether more of the part should be made now, and how many runs."""
    return logic.suggest(
        stock=numbers['stock'],
        incoming=numbers['incoming'],
        demand=numbers['demand'],
        minimum=numbers['minimum'],
        restock_to=link.get('restock_to'),
        per_run=float(link.get('parts_per_run') or 1),
    )
