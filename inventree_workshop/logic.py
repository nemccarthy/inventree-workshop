"""The rules of the plugin, as plain Python (no InvenTree or Django imports).

- how many runs of a machine a quantity needs
- whether more of a part should be made now, and how many runs
- what state a job is in
- how much material a booking uses
"""

from __future__ import annotations

import math

# Job states
OPEN = 'open'  # raised, nothing booked yet
PARTIAL = 'partial'  # some parts are in stock, the rest is still to make
DONE = 'done'
CANCELLED = 'cancelled'

REASON_LOW_STOCK = 'low_stock'
REASON_BUILD_DEMAND = 'build_demand'

_EPSILON = 1e-9


def runs_for(quantity: float, per_run: float) -> int:
    """Number of runs needed to make at least the given quantity."""
    if per_run <= 0:
        raise ValueError('Parts per run must be greater than zero')

    if quantity <= 0:
        return 0

    return int(math.ceil(quantity / per_run - _EPSILON))


def suggest(
    *,
    stock: float,
    incoming: float,
    demand: float,
    minimum: float,
    restock_to: float | None,
    per_run: float,
) -> dict:
    """Work out whether more of a part should be made now, and how many runs.

    Arguments:
        stock: quantity in stock
        incoming: quantity still to come from open build orders for the part
            (workshop jobs which are open count here, so the same shortage
            is never suggested twice)
        demand: quantity which open build orders still need of the part
        minimum: minimum stock of the part
        restock_to: level to make up to (never less than the minimum)
        per_run: good parts from one run

    The projected stock is stock + incoming - demand. Making more is
    suggested when that is below the minimum stock (zero when no minimum is set).

    Nothing is ever started from this: it is only what the pages show.
    """
    available = stock + incoming
    projected = available - demand
    floor = max(0.0, minimum)

    result = {
        'stock': stock,
        'incoming': incoming,
        'demand': demand,
        'projected': projected,
        'floor': floor,
        'target': floor,
        'shortfall': 0.0,
        'runs': 0,
        'quantity': 0.0,
        'reason': None,
    }

    if projected >= floor - _EPSILON:
        return result

    target = floor

    if restock_to is not None:
        target = max(floor, restock_to)

    shortfall = target - projected
    runs = runs_for(shortfall, per_run)

    # Why: without the build orders, would the stock have been enough?
    reason = REASON_LOW_STOCK if available < floor - _EPSILON else REASON_BUILD_DEMAND

    result.update({
        'target': target,
        'shortfall': shortfall,
        'runs': runs,
        'quantity': runs * per_run,
        'reason': reason,
    })

    return result


def summarise(
    *,
    quantity: float,
    completed: float,
    per_run: float,
    bookings: list[dict],
    build_state: str = 'active',
    closed: bool = False,
) -> dict:
    """State of a job.

    Arguments:
        quantity: quantity of the build order
        completed: quantity which has been booked into stock
        per_run: good parts from one run
        bookings: what has been booked so far: [{"good": 18, "runs": 1}, ...]
        build_state: 'active', 'complete' or 'cancelled' (the build order)
        closed: the plugin has closed the job (the build order may still be
            completing in the background)
    """
    per_run = per_run if per_run > 0 else 1.0
    remaining = max(0.0, quantity - completed)
    runs_done = sum(int(entry.get('runs') or 0) for entry in bookings)
    made = runs_done * per_run
    rejected = max(0.0, made - sum(float(entry.get('good') or 0) for entry in bookings))

    if build_state == 'cancelled':
        state = CANCELLED
    elif build_state == 'complete' or closed:
        state = DONE
    elif completed > 0 or runs_done > 0:
        state = PARTIAL
    else:
        state = OPEN

    active = state in (OPEN, PARTIAL)

    return {
        'state': state,
        'remaining': remaining,
        'runs_planned': runs_for(quantity, per_run),
        'runs_done': runs_done,
        'runs_left': runs_for(remaining, per_run) if active else 0,
        'rejected': rejected,
        'can_book': active,
        # Complete the build order with what is in stock, even if that is
        # fewer parts than it asked for
        'can_close': active and completed > 0,
        # Nothing is in stock yet, so the build order can simply be cancelled
        'can_cancel': active and completed <= 0,
    }


def check_booking(good, runs, per_run: float) -> str | None:
    """Why a booking cannot be accepted, or None if it can."""
    try:
        good = float(good)
        runs = float(runs)
    except (TypeError, ValueError):
        return 'Enter the number of runs and the number of good parts'

    if runs != int(runs) or runs < 1:
        return 'The number of runs must be a whole number, one or more'

    if good != int(good) or good < 0:
        return 'The number of good parts must be a whole number, zero or more'

    limit = runs * per_run

    if good > limit + _EPSILON:
        return (
            f'{good:g} good parts is more than {runs:g} '
            f'{"run" if runs == 1 else "runs"} of {per_run:g} can give ({limit:g}). '
            'Raise the number of runs.'
        )

    return None


def material_for(per_part: float, runs: float, per_run: float) -> float:
    """Material which a number of runs uses.

    A run uses the material of every part on it, whether the part turns out
    good or not: the bill of materials quantity (per part) times the parts on
    a run times the runs.
    """
    return round(max(0.0, per_part) * max(0.0, runs) * max(0.0, per_run), 5)


def split_stock(wanted: float, items: list[tuple]) -> tuple[list[tuple], float]:
    """Share a quantity out over stock items, in the order given.

    'items' is [(id, available), ...]. Returns ([(id, quantity), ...], short)
    where 'short' is what the stock could not cover.
    """
    taken = []
    left = wanted

    for key, available in items:
        if left <= _EPSILON:
            break

        if available <= _EPSILON:
            continue

        quantity = min(left, available)
        taken.append((key, quantity))
        left -= quantity

    return taken, max(0.0, left) if left > _EPSILON else 0.0
