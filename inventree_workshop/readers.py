"""What a job file says about itself, in one form whatever kind of file it is.

Plain Python (no InvenTree imports). Two kinds of file are read:

- xTool project files (.xcs), see xcs.py
- G-code programs (.nc, .gcode, ...), see gcode.py

Every other file (a CAM project, a drawing, a photo of the fixture) is stored
and handed back all the same, without details.

    {
        "recognised": true,
        "kind": "xcs",                 # "xcs", "gcode" or ""
        "kind_name": "xTool project",
        "size": 12063,
        "facts": ["xTool S1", "112 × 67 mm", "1.1 mm thick"],
        "operations": [                # shown as badges
            {"label": "Cut × 20", "detail": "35% · 60 mm/s", "tone": "cut"}
        ],
        "notes": ["..."],              # anything worth a sentence
        "parts_hint": 20,              # a guess at the parts from one run
        "parts_hint_text": "20 shapes are set to cut in the file",
        "minutes_hint": null,          # running time the file itself gives
        "has_cover": true              # a preview picture is stored in the file
    }
"""

from __future__ import annotations

from . import gcode, xcs

KIND_NAMES = {'xcs': 'xTool project', 'gcode': 'G-code program'}


def kind_of(filename: str | None) -> str:
    """The kind of file, from its name: 'xcs', 'gcode' or ''."""
    if xcs.is_project_name(filename):
        return 'xcs'

    if gcode.is_gcode_name(filename):
        return 'gcode'

    return ''


def _num(value) -> str:
    """A number as people write it: 12000 -> '12,000', 1.10 -> '1.1'."""
    if value is None:
        return ''

    value = float(value)

    if value == int(value):
        return f'{int(value):,}'

    return f'{value:,.2f}'.rstrip('0').rstrip('.')


def _empty(kind: str, size: int) -> dict:
    return {
        'recognised': False,
        'kind': kind,
        'kind_name': KIND_NAMES.get(kind, ''),
        'size': size,
        'facts': [],
        'operations': [],
        'notes': [],
        'parts_hint': None,
        'parts_hint_text': '',
        'minutes_hint': None,
        'has_cover': False,
    }


def describe(content: bytes | None, filename: str | None, size: int | None = None) -> dict:
    """Describe a file. 'content' is None for a file too big to be read."""
    kind = kind_of(filename)
    result = _empty(kind, size if size is not None else len(content or b''))

    if content is None:
        result['notes'].append('The file is too big to be read for its details.')
        return result

    try:
        if kind == 'xcs':
            _describe_xcs(result, xcs.summarise(content, filename))
        elif kind == 'gcode':
            _describe_gcode(result, gcode.summarise(content, filename))
    except Exception:  # noqa: BLE001 - a description is never worth an error
        return _empty(kind, result['size'])

    return result


def _describe_xcs(result: dict, summary: dict) -> None:
    if not summary.get('recognised'):
        return

    result['recognised'] = True
    result['has_cover'] = bool(summary.get('has_cover'))

    if summary.get('machine'):
        result['facts'].append(f"xTool {summary['machine']}")

    if summary.get('width') and summary.get('height'):
        result['facts'].append(f"{_num(summary['width'])} × {_num(summary['height'])} mm")

    if summary.get('thickness'):
        result['facts'].append(f"{_num(summary['thickness'])} mm thick")

    if summary.get('material'):
        result['facts'].append(summary['material'])

    for operation in summary.get('operations') or []:
        settings = []

        if operation.get('power') is not None:
            settings.append(f"{_num(operation['power'])}%")

        if operation.get('speed') is not None:
            settings.append(f"{_num(operation['speed'])} mm/s")

        if (operation.get('passes') or 0) > 1:
            settings.append(f"{_num(operation['passes'])} passes")

        result['operations'].append({
            'label': f"{operation['label']} × {_num(operation['count'])}",
            'detail': ' · '.join(settings),
            'tone': 'cut' if operation.get('type') == 'VECTOR_CUTTING' else 'other',
        })

    if not result['operations']:
        result['notes'].append('No shapes are set to be processed in this file.')

    if (summary.get('canvases') or 1) > 1:
        result['notes'].append(
            f"The project has {summary['canvases']} canvases. This is the one which was open when it was saved."
        )

    cut = summary.get('cut_shapes') or 0

    if cut > 0:
        result['parts_hint'] = cut
        result['parts_hint_text'] = (
            f"{_num(cut)} {'shape is' if cut == 1 else 'shapes are'} set to cut in the file"
        )


def _describe_gcode(result: dict, summary: dict) -> None:
    if not summary.get('recognised'):
        return

    result['recognised'] = True

    if summary.get('made_for'):
        result['facts'].append(f"for {summary['made_for']}")

    spans = [value for value in (summary.get('width'), summary.get('height')) if value]
    depth = summary.get('depth')

    if spans:
        # A program which turns the part on the rotary axis only travels along one axis
        travel = ' × '.join(_num(value) for value in spans) + ' mm'

        if len(spans) == 1:
            travel += ' of travel'

        if depth:
            travel += f', {_num(depth)} mm deep'

        result['facts'].append(travel)

    if summary.get('material'):
        result['facts'].append(summary['material'])
    elif summary.get('stock'):
        result['facts'].append('stock ' + ' × '.join(_num(size) for size in summary['stock']) + ' mm')

    if summary.get('spindle_max'):
        result['facts'].append(f"up to {_num(summary['spindle_max'])} rpm")

    if summary.get('feed_max'):
        result['facts'].append(f"feed up to {_num(summary['feed_max'])} mm/min")

    if summary.get('rotary'):
        result['facts'].append('uses the rotary axis')

    if summary.get('seconds'):
        minutes = max(1, round(summary['seconds'] / 60))
        result['minutes_hint'] = minutes
        result['facts'].append(f'about {_num(minutes)} min')

    result['facts'].append(f"{_num(summary['lines'])} lines")

    names = summary.get('tool_names') or {}

    for tool in summary.get('tools') or []:
        # JSON turns the keys of a stored summary into text
        name = names.get(tool) or names.get(str(tool)) or ''
        result['operations'].append({'label': f'Tool {tool}', 'detail': name, 'tone': 'other'})

    if summary.get('partial'):
        result['notes'].append(
            f"Only the first {_num(summary['lines'])} lines were read: tools and travel further on are not shown."
        )


def cover(content: bytes | None, filename: str | None) -> tuple[bytes, str] | None:
    """The preview picture stored in a file, if its kind has one."""
    if content is None or kind_of(filename) != 'xcs':
        return None

    return xcs.cover(content)
