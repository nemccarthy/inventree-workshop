"""Workshop jobs.

A job is an InvenTree build order for a part which is made in-house on a
machine. Nothing is sent to the machine: somebody takes the files of the
part, sets the machine up and runs it, then books what came out. What the
plugin knows about a job is stored in the metadata of the build order, under
the key 'workshop':

    {
        "machine": {"id": 2, "name": "Makera Carvera", "kind": "cnc"},
        "files": [{"attachment": 31, "filename": "plate_side-a.nc",
                   "label": "Side A", "file_hash": "9f2c..."}],
        "parts_per_run": 4,
        "run_minutes": 25,
        "runs": 3,                      # runs planned when the job was raised
        "source": "manual",
        "bookings": [                   # what has been made and booked
            {"good": 4, "runs": 1, "by": "nate", "at": "...", "location": 7,
             "material": [{"part": 12, "name": "Aluminium plate", "quantity": 1.0}]}
        ],
        "closed": false
    }

The build order is what the rest of InvenTree sees: while it is open, the
quantity still to come counts as incoming stock.

Material: if the part has a bill of materials, the build order has a line
for each material. When parts are booked, the material which the runs used is
taken from stock against those lines (allocated and consumed in one step).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from . import logic
from .links import KEY, check_files, get_link

logger = logging.getLogger('inventree')

SOURCE_MANUAL = 'manual'

# The most runs one job may ask for, as a guard against typing errors
RUN_LIMIT = 500

NOTE_LIMIT = 250


class JobError(Exception):
    """A job could not be created or changed."""


def job_meta(build) -> dict | None:
    """The plugin's data on a build order, or None if it is not a workshop job."""
    metadata = build.metadata if isinstance(build.metadata, dict) else {}
    meta = metadata.get(KEY)

    if isinstance(meta, dict) and 'bookings' in meta:
        return meta

    return None


def _now() -> str:
    from django.utils import timezone

    return timezone.now().isoformat(timespec='seconds')


def _builds():
    from build.models import Build

    return Build.objects.filter(metadata__has_key=KEY).select_related(
        'part', 'issued_by', 'destination'
    )


def is_finished(build, meta: dict) -> bool:
    """True once a job is over.

    The plugin marks a job when it closes or cancels it, because InvenTree
    may complete the build order itself a moment later, in the background.
    """
    from build.status_codes import BuildStatusGroups

    if meta.get('closed') or meta.get('cancelled'):
        return True

    return build.status not in BuildStatusGroups.ACTIVE_CODES


def active_jobs(part=None) -> list:
    """Jobs which are still open, oldest first."""
    from build.status_codes import BuildStatusGroups

    builds = _builds().filter(status__in=BuildStatusGroups.ACTIVE_CODES)

    if part is not None:
        builds = builds.filter(part=part)

    result = []

    for build in builds.order_by('pk'):
        meta = job_meta(build)

        if meta is not None and not is_finished(build, meta):
            result.append(build)

    return result


def recent_jobs(part=None, limit: int = 20, finished_only: bool = False) -> list:
    """The latest jobs, newest first."""
    builds = _builds()

    if part is not None:
        builds = builds.filter(part=part)

    result = []

    for build in builds.order_by('-pk')[: limit * 4]:
        meta = job_meta(build)

        if meta is None or (finished_only and not is_finished(build, meta)):
            continue

        result.append(build)

        if len(result) >= limit:
            break

    return result


def get_job(pk: int):
    """The job with the given build order id, or None."""
    build = _builds().filter(pk=pk).first()

    if build is None or job_meta(build) is None:
        return None

    return build


def _mutate(build, change):
    """Change a job under a row lock on its build order, all or nothing.

    'change' is called with the locked build order and the plugin's data,
    which it edits in place. Whatever it does to stock is undone if it raises.
    Only the metadata column is written here, so that this never overwrites a
    status which InvenTree is changing at the same moment.
    """
    from build.models import Build
    from django.db import transaction

    with transaction.atomic():
        locked = Build.objects.select_for_update().get(pk=build.pk)
        meta = job_meta(locked) or {'bookings': []}

        result = change(locked, meta)

        metadata = dict(locked.metadata) if isinstance(locked.metadata, dict) else {}
        metadata[KEY] = meta
        locked.metadata = metadata
        locked.save(update_fields=['metadata'])

    build.refresh_from_db()

    return result


def _build_state(build, meta: dict) -> str:
    from build.status_codes import BuildStatus

    if build.status == BuildStatus.CANCELLED.value or meta.get('cancelled'):
        return 'cancelled'

    if build.status == BuildStatus.COMPLETE.value:
        return 'complete'

    return 'active'


def summary(build, meta: dict | None = None) -> dict:
    """State of a job (see logic.summarise)."""
    meta = meta if meta is not None else (job_meta(build) or {'bookings': []})

    return logic.summarise(
        quantity=float(build.quantity),
        completed=float(build.completed),
        per_run=float(meta.get('parts_per_run') or 1),
        bookings=meta.get('bookings') or [],
        build_state=_build_state(build, meta),
        closed=bool(meta.get('closed')),
    )


# Material


def _stock_items(part, build) -> list:
    """Stock of a material which can be taken: [(stock item, available)].

    Stock in the source location of the build order comes first, then the
    oldest stock.
    """
    from stock.models import StockItem
    from stock.status_codes import StockStatusGroups

    items = StockItem.objects.filter(
        StockItem.IN_STOCK_FILTER,
        part=part,
        status__in=StockStatusGroups.AVAILABLE_CODES,
    ).order_by('pk')

    preferred = set()

    if build.take_from_id:
        preferred = set(
            build.take_from.get_descendants(include_self=True).values_list('pk', flat=True)
        )

    result = []

    for item in items:
        available = float(item.unallocated_quantity())

        if available > 0:
            result.append((item, available))

    result.sort(key=lambda entry: (entry[0].location_id not in preferred, entry[0].pk))

    return result


def material_lines(build, meta: dict | None = None) -> list:
    """The materials of a job: the lines of its build order which take stock.

    Consumable lines are left out (InvenTree does not take those from stock),
    and so are materials tracked by serial number.
    """
    from build.models import BuildLine

    meta = meta if meta is not None else (job_meta(build) or {})
    per_run = float(meta.get('parts_per_run') or 1)
    total = float(build.quantity) or 1.0

    lines = (
        BuildLine.objects.filter(build=build)
        .select_related('bom_item', 'bom_item__sub_part')
        .order_by('pk')
    )

    result = []

    for line in lines:
        bom_item = line.bom_item
        material = bom_item.sub_part if bom_item else None

        if material is None or bom_item.consumable or material.trackable or material.virtual:
            continue

        # What the build order needs for one part, with any allowance for waste
        per_part = float(line.quantity) / total

        result.append({
            'line': line.pk,
            'part': material.pk,
            'name': material.name,
            'ipn': material.IPN or '',
            'units': material.units or '',
            'per_part': round(per_part, 6),
            'per_run': logic.material_for(per_part, 1, per_run),
            'required': float(line.quantity),
            'consumed': float(line.consumed),
            'in_stock': round(sum(available for _, available in _stock_items(material, build)), 5),
        })

    return result


def _consume(build, meta: dict, material, runs: int, user) -> list:
    """Take the material which the runs used from stock, against the build order.

    'material' is [{"line": <build line id>, "quantity": 1.5}, ...]. A line
    which is left out uses what the bill of materials says; None does that
    for every line. A quantity of zero takes nothing.
    """
    from build.models import BuildItem, BuildLine

    lines = material_lines(build, meta)
    known = {entry['line']: entry for entry in lines}
    wanted: dict = {}

    for entry in material or []:
        if not isinstance(entry, dict):
            raise JobError('The material used is not in the form the plugin expects')

        try:
            line = int(entry.get('line'))
            quantity = float(entry.get('quantity') or 0)
        except (TypeError, ValueError):
            raise JobError('Enter the quantity of material used as a number') from None

        if line not in known:
            raise JobError('This material is not on the bill of materials of the build order')

        if quantity < 0 or quantity != quantity:
            raise JobError('The quantity of material used cannot be negative')

        wanted[line] = round(quantity, 5)

    for entry in lines:
        wanted.setdefault(entry['line'], logic.material_for(entry['per_part'], runs, float(meta.get('parts_per_run') or 1)))

    allocations = []
    used = []

    for entry in lines:
        quantity = wanted[entry['line']]

        if quantity <= 0:
            continue

        line = BuildLine.objects.select_related('bom_item__sub_part').get(pk=entry['line'])
        stock_items = _stock_items(line.bom_item.sub_part, build)
        by_pk = {item.pk: item for item, _ in stock_items}

        taken, short = logic.split_stock(
            quantity, [(item.pk, available) for item, available in stock_items]
        )

        if short > 0:
            units = f" {entry['units']}" if entry['units'] else ''

            raise JobError(
                f"There is not enough {entry['name']} in stock: {quantity:g}{units} to take, "
                f"{quantity - short:g}{units} free. Receive the stock first, or change the quantity used."
            )

        for pk, amount in taken:
            item = BuildItem(
                build_line=line,
                stock_item=by_pk[pk],
                quantity=Decimal(str(round(amount, 5))),
            )
            item.save()
            allocations.append(item.pk)

        used.append({
            'part': entry['part'],
            'name': entry['name'],
            'units': entry['units'],
            'quantity': quantity,
        })

    if allocations:
        build.complete_allocations(
            BuildItem.objects.filter(pk__in=allocations),
            user=user,
            notes=f'Workshop job {build.reference}',
        )

    return used


# Describing a job


def describe(build) -> dict:
    """A job, as sent to the user interface."""
    meta = job_meta(build) or {'bookings': []}
    part = build.part
    state = summary(build, meta)
    active = state['state'] in (logic.OPEN, logic.PARTIAL)

    return {
        'build': build.pk,
        'reference': build.reference,
        'title': build.title,
        'part': part.pk,
        'part_name': part.name,
        'part_ipn': part.IPN or '',
        'quantity': float(build.quantity),
        'completed': float(build.completed),
        'build_status': build.status,
        'created': build.creation_date.isoformat() if build.creation_date else None,
        'target_date': build.target_date.isoformat() if build.target_date else None,
        'issued_by': build.issued_by.username if build.issued_by else None,
        'destination': build.destination_id,
        'destination_name': build.destination.pathstring if build.destination else None,
        'source': meta.get('source') or SOURCE_MANUAL,
        'machine': meta.get('machine') or None,
        'files': meta.get('files') or [],
        'parts_per_run': meta.get('parts_per_run'),
        'run_minutes': meta.get('run_minutes'),
        'runs': meta.get('runs'),
        'notes': meta.get('notes') or '',
        'bookings': meta.get('bookings') or [],
        'material': material_lines(build, meta) if active else [],
        'summary': state,
    }


# Creating a job


def create_job(
    plugin,
    part,
    runs: int,
    machine: dict | None,
    user=None,
    *,
    notes: str = '',
    source: str = SOURCE_MANUAL,
):
    """Raise a build order for a number of runs of the part on its machine.

    'machine' is the machine of the part's link, or None if it was removed.
    """
    link = get_link(part)

    if not link:
        raise JobError('This part is not linked to a machine and its files')

    if machine is None:
        raise JobError(
            'The machine of this part no longer exists. Edit the link and choose a machine first.'
        )

    if runs < 1:
        raise JobError('Nothing to make: the number of runs must be at least one')

    if runs > RUN_LIMIT:
        raise JobError(f'{runs} runs is more than one job can ask for ({RUN_LIMIT})')

    checked = check_files(part, link)
    gone = [
        entry.get('filename')
        for entry, state in zip(link['files'], checked)
        if state['missing']
    ]

    if gone:
        names = ', '.join(f"'{name}'" for name in gone)

        raise JobError(
            f"{names} {'is' if len(gone) == 1 else 'are'} no longer attached to the part. Edit the link and choose the files again first."
        )

    build = new_build(plugin, part, link, machine, runs, user)

    meta = {
        'machine': {'id': machine['id'], 'name': machine['name'], 'kind': machine.get('kind')},
        # The files as they are now: a job always records what it was made from
        'files': [
            {
                'attachment': entry['attachment'],
                'filename': entry.get('filename'),
                'label': entry.get('label') or '',
                'file_hash': state['file_hash'] or entry.get('file_hash'),
                'changed': state['changed'],
            }
            for entry, state in zip(link['files'], checked)
        ],
        'parts_per_run': link['parts_per_run'],
        'run_minutes': link.get('run_minutes'),
        'runs': runs,
        'source': source,
        'notes': str(notes or '').strip()[:NOTE_LIMIT],
        'bookings': [],
        'created': _now(),
    }

    def store(locked, stored):
        stored.clear()
        stored.update(meta)

    _mutate(build, store)

    # In production from the start: the parts are on their way
    try:
        build.issue_build()
    except Exception:  # pragma: no cover - the job itself is in place
        logger.exception('Workshop: could not issue build order %s', build.reference)

    build.refresh_from_db()

    return build


def new_build(plugin, part, link: dict, machine: dict, runs: int, user):
    """Create the (pending) build order of a job."""
    import datetime

    import InvenTree.helpers
    from build.models import Build
    from django.core.exceptions import ValidationError
    from stock.models import StockLocation

    per_run = int(link['parts_per_run'])
    plural = 'run' if runs == 1 else 'runs'

    destination = None

    if link.get('destination'):
        destination = StockLocation.objects.filter(pk=link['destination']).first()

    if destination is None:
        destination = part.get_default_location() or plugin.default_location()

    lead_days = max(0, plugin.int_setting('LEAD_DAYS', 1))
    today = InvenTree.helpers.current_date()

    build = Build(
        part=part,
        quantity=runs * per_run,
        title=f"{machine['name']}: {runs} {plural} of {part.name}"[:100],
        issued_by=user,
        destination=destination,
        start_date=today,
        target_date=today + datetime.timedelta(days=lead_days),
    )

    # Marks the build order as a workshop job from the moment it exists
    build.metadata = {KEY: {'bookings': [], 'pending': True}}

    try:
        build.save()
    except ValidationError as exc:
        raise JobError('InvenTree refused the build order: ' + '; '.join(exc.messages)) from None

    return build


# Booking what was made


def book(
    plugin,
    build,
    good,
    runs,
    user,
    *,
    location=None,
    notes: str = '',
    material=None,
    finish: bool = False,
) -> dict:
    """Book the good parts of a number of runs into stock.

    Creates a build output for the good parts and completes it into stock, and
    takes the material which the runs used from stock. When the build order
    has its quantity it is completed. With 'finish' it is completed (or, if
    nothing good came out at all, cancelled) even when it is short.
    """
    from django.core.exceptions import ValidationError

    before = job_meta(build) or {}
    per_run = float(before.get('parts_per_run') or 1)
    made_note = f"Made on {(before.get('machine') or {}).get('name') or 'a workshop machine'}"
    problem = logic.check_booking(good, runs, per_run)

    if problem:
        raise JobError(problem)

    good = Decimal(int(float(good)))
    runs = int(float(runs))
    outcome: dict = {}

    def apply(locked, meta):
        state = summary(locked, meta)

        if not state['can_book']:
            raise JobError('This job is closed')

        target = location or locked.destination or locked.part.get_default_location()

        try:
            used = _consume(locked, meta, material, runs, user)

            if good > 0:
                output = locked.create_build_output(good, user=user, location=target).first()
                locked.complete_build_output(
                    output, user, location=target, notes=notes or made_note
                )
        except ValidationError as exc:
            raise JobError('InvenTree refused the stock: ' + '; '.join(exc.messages)) from None

        meta.setdefault('bookings', []).append({
            'good': float(good),
            'runs': runs,
            'by': user.username if user else None,
            'at': _now(),
            'location': target.pk if target else None,
            'material': used,
            'notes': notes,
        })
        meta.pop('pending', None)

        outcome.update({'good': float(good), 'runs': runs, 'material': used})

    _mutate(build, apply)

    state = summary(build)
    outcome['closed'] = False
    outcome['cancelled'] = False

    if state['remaining'] <= 0 or (finish and build.completed > 0):
        outcome['closed'] = close(build, user)
    elif finish:
        # Nothing good came out: there is nothing to complete
        outcome['cancelled'] = cancel(build, user)['build_cancelled']

    return outcome


def close(build, user) -> bool:
    """Complete the build order with what has been booked so far."""
    from django.core.exceptions import ValidationError

    state = summary(build)

    if state['state'] in (logic.DONE, logic.CANCELLED):
        return False

    if build.completed <= 0:
        raise JobError('Nothing has been booked into stock yet. Cancel the job instead.')

    try:
        build.complete_build(user)
    except ValidationError as exc:
        raise JobError(
            'InvenTree refused to complete the build order: ' + '; '.join(exc.messages)
        ) from None
    except Exception as exc:
        raise JobError(f'InvenTree could not complete the build order: {exc}') from None

    def mark(locked, meta):
        meta['closed'] = True
        meta['closed_at'] = _now()

    _mutate(build, mark)

    return True


def cancel(build, user) -> dict:
    """Cancel a job which has nothing in stock yet."""
    state = summary(build)

    if state['state'] in (logic.DONE, logic.CANCELLED):
        return {'build_cancelled': False}

    if build.completed > 0:
        raise JobError('Parts of this job are in stock already. Close the job instead.')

    try:
        build.cancel_build(user)
    except Exception as exc:
        raise JobError(f'InvenTree could not cancel the build order: {exc}') from None

    def mark(locked, meta):
        meta['cancelled'] = True
        meta['closed_at'] = _now()

    _mutate(build, mark)

    return {'build_cancelled': True}
