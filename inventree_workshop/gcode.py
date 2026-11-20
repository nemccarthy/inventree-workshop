"""Reading G-code programs (.nc, .gcode, ...), as plain Python (no InvenTree imports).

This is the file a CNC mill such as the Makera Carvera runs. It is read to
show people what the program does: which tools it calls, how fast the spindle
turns, and how far the cutter travels. Nothing here is needed to run a job:
the file is stored and handed back unchanged, and a program which is not
understood simply has no details.

The travel is worked out from the end points of the cutting moves (G1, G2,
G3) in the program's own coordinates. Arcs are measured at their end points,
so the true extent of a program made of large arcs can be a little bigger.

Programs written by Makera's own CAM software start with a header of comment
lines which say what the program is for:

    ;@MKR|MACHINE|id=Z1|name=Makera Z1
    ;@MKR|MATERIAL|id=...|name=6061 Aluminum Sheet Plate - 5mm
    ;@MKR|STOCK|id=cuboid|length=100|width=100|height=5
    ;@MKR|TOOL|number=1|name=3.175*12mm Flat End(Metal)|...
    ;@MKR|TIME|seconds=1750

When it is there, the names of the tools, the material and the running time
are taken from it.
"""

from __future__ import annotations

import re

# File names which are taken to be G-code
EXTENSIONS = ('.nc', '.gcode', '.cnc', '.ngc', '.tap', '.gc', '.g')

# Lines read for the summary. A program can run to millions of lines (3D
# surfaces); the first part says which tools it uses and roughly how big it is.
LINE_LIMIT = 200000

_COMMENT = re.compile(r'\([^)]*\)|;.*$')
_WORD = re.compile(r'([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))')

_INCH = 25.4

# A coordinate beyond this (in mm) is a damaged line, not a move
_REACH = 10000.0

_HEADER = ';@MKR|'
_TEXT_LIMIT = 80


def is_gcode_name(filename: str | None) -> bool:
    """True if the file name is that of a G-code program."""
    return str(filename or '').lower().endswith(EXTENSIONS)


def summarise(content: bytes, filename: str | None = None) -> dict:
    """What a G-code program does, for display. Lengths are in millimetres."""
    result = {'recognised': False, 'size': len(content or b'')}

    try:
        result.update(_read(content or b''))
    except Exception:  # noqa: BLE001 - a summary is never worth an error
        return {'recognised': False, 'size': len(content or b'')}

    return result


def _read(content: bytes) -> dict:
    if b'\x00' in content[:4096]:
        # Binary: not a program
        return {'recognised': False}

    text = content.decode('utf-8', errors='replace')

    absolute = True
    scale = 1.0
    units = None
    motion = None
    position = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
    known = {'X': False, 'Y': False, 'Z': False}
    low = {'X': None, 'Y': None, 'Z': None}
    high = {'X': None, 'Y': None, 'Z': None}

    tools: list[int] = []
    tool_changes = 0
    spindle = 0.0
    feed = 0.0
    rotary = False
    commands = 0
    lines = 0
    partial = False

    header: dict = {'tool_names': {}, 'toolpaths': []}

    for raw in text.splitlines():
        lines += 1

        if lines > LINE_LIMIT:
            partial = True
            break

        if raw.startswith(_HEADER):
            _read_header(raw, header)
            continue

        line = _COMMENT.sub('', raw.upper()).strip()

        if not line or line.startswith('%'):
            continue

        words = _WORD.findall(line)

        if not words:
            continue

        codes = [(letter, float(value)) for letter, value in words]
        g_codes = [value for letter, value in codes if letter == 'G']
        m_codes = [value for letter, value in codes if letter == 'M']

        if g_codes or m_codes:
            commands += 1

        for value in g_codes:
            if value == 90:
                absolute = True
            elif value == 91:
                absolute = False
            elif value == 20:
                scale, units = _INCH, 'inch'
            elif value == 21:
                scale, units = 1.0, 'mm'
            elif value in (0, 1, 2, 3):
                motion = int(value)

        for letter, value in codes:
            if letter == 'T' and value == int(value) and value >= 0:
                if int(value) not in tools:
                    tools.append(int(value))
            elif letter == 'S':
                spindle = max(spindle, value)
            elif letter == 'F':
                feed = max(feed, value * scale)
            elif letter in ('A', 'B') and motion is not None:
                rotary = True

        if 6 in m_codes:
            tool_changes += 1

        # Moves in machine coordinates and homing say nothing about the part
        if any(value in (28, 30, 53, 92, 10) for value in g_codes):
            continue

        moved = False

        for letter, value in codes:
            if letter in position:
                if abs(value * scale) > _REACH:
                    continue

                position[letter] = value * scale if absolute else position[letter] + value * scale
                known[letter] = True
                moved = True

        if moved and motion in (1, 2, 3):
            for axis in position:
                # An axis the program has not placed yet says nothing
                if not known[axis]:
                    continue

                value = position[axis]
                low[axis] = value if low[axis] is None else min(low[axis], value)
                high[axis] = value if high[axis] is None else max(high[axis], value)

    if commands < 3:
        return {'recognised': False}

    def span(axis):
        if low[axis] is None:
            return None

        return round(high[axis] - low[axis], 2)

    return {
        'recognised': True,
        'lines': lines if not partial else LINE_LIMIT,
        'partial': partial,
        'units': units,
        'tools': tools,
        'tool_changes': tool_changes,
        'spindle_max': spindle or None,
        'feed_max': round(feed, 1) or None,
        'width': span('X'),
        'height': span('Y'),
        # How far below the program's zero the cutter goes
        'depth': round(-low['Z'], 2) if low['Z'] is not None and low['Z'] < 0 else None,
        'rotary': rotary,
        # From the header of Makera's CAM software, when the program has one
        'made_for': header.get('machine'),
        'material': header.get('material'),
        'stock': header.get('stock'),
        'seconds': header.get('seconds'),
        'tool_names': header['tool_names'],
        'toolpaths': header['toolpaths'],
    }


def _clip(value) -> str | None:
    text = ' '.join(str(value or '').split())

    return text[:_TEXT_LIMIT] or None


def _positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number != number or number <= 0 or number > 1e9:
        return None

    return number


def _read_header(line: str, header: dict) -> None:
    """One line of the header which Makera's CAM software writes."""
    fields = line.strip().split('|')

    if len(fields) < 2:
        return

    key = fields[1].strip().upper()
    values = dict(field.split('=', 1) for field in fields[2:] if '=' in field)

    if key == 'MACHINE':
        header['machine'] = _clip(values.get('name'))
    elif key == 'MATERIAL':
        header['material'] = _clip(values.get('name'))
    elif key == 'STOCK':
        sizes = [_positive(values.get(name)) for name in ('length', 'width', 'height')]

        if all(sizes):
            header['stock'] = [round(size, 2) for size in sizes]
    elif key == 'TIME':
        header['seconds'] = _positive(values.get('seconds'))
    elif key == 'TOOL':
        number = _positive(values.get('number'))
        name = _clip(values.get('name'))

        if number is not None and number == int(number) and name and len(header['tool_names']) < 50:
            header['tool_names'][int(number)] = name
    elif key == 'TOOLPATH':
        name = _clip(values.get('name'))

        if name and len(header['toolpaths']) < 50:
            header['toolpaths'].append(name)
