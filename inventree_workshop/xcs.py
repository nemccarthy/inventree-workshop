"""Reading xTool project files (.xcs), as plain Python (no InvenTree imports).

A .xcs file is the project format of xTool Creative Space and xTool Studio. It
is a JSON document. xTool does not publish the format, so what is read here
comes from looking at project files:

    {
      "canvasId": "...",                      # the canvas which is open
      "extId": "D1Pro", "version": "2.2.23", "modify": 1733344934779,
      "cover": "data:image/png;base64,...",   # preview picture of the project
      "canvas": [
        {"id": "...", "title": "...",
         "displays": [                        # the shapes, sizes in mm
           {"id": "...", "type": "RECT", "x": 0, "y": 0, "width": 10, "height": 5}
         ]}
      ],
      "device": {
        "id": "D1Pro",
        "materialList": [{"id": 11, "name": {"en": "..."}}],
        "data": {"dataType": "Map", "value": [
          ["<canvas id>", {
            "mode": "LASER_PLANE",
            "data": {"LASER_PLANE": {"material": 11, "thickness": 0.2}},
            "displays": {"dataType": "Map", "value": [
              ["<shape id>", {
                "processingType": "VECTOR_CUTTING",
                "processIgnore": false,
                "data": {"VECTOR_CUTTING": {
                  "materialType": "customize",
                  "parameter": {"customize": {"power": 80, "speed": 10, "repeat": 1}}
                }}
              }]
            ]}
          }]
        ]}
      }
    }

Nothing here is needed to run a job: the file is stored and handed back
unchanged. The summary is for people, so that they can see which file is
linked and what it will do. Reading therefore never fails: a file which is not
understood gives a summary with 'recognised' False.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import io
import json
import zipfile

# Project files of xTool Creative Space / xTool Studio
PROJECT_EXTENSIONS = ('.xcs', '.xs')

# What xTool calls the ways of processing a shape
OPERATIONS = {
    'VECTOR_CUTTING': 'Cut',
    'VECTOR_ENGRAVING': 'Score',
    'FILL_VECTOR_ENGRAVING': 'Engrave',
    'COLOR_FILL_ENGRAVE': 'Engrave',
    'BITMAP_ENGRAVING': 'Engrave image',
    'KNIFE_CUTTING': 'Blade cut',
    'RELIEF': 'Relief',
    'INTAGLIO': 'Intaglio',
}

# Shown in this order
_ORDER = list(OPERATIONS)

# Largest file which is read for its summary. Bigger files are still stored.
READ_LIMIT = 64 * 1024 * 1024

# Largest preview picture which is passed on
COVER_LIMIT = 4 * 1024 * 1024

_IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')


def is_project_name(filename: str | None) -> bool:
    """True if the file name is that of an xTool project file."""
    return str(filename or '').lower().endswith(PROJECT_EXTENSIONS)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    if value != value or value in (float('inf'), float('-inf')):
        return None

    return float(value)


def _text(value, limit: int = 120) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:limit]

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)

    return None


def _map_entries(value) -> list:
    """The [key, value] pairs of a serialised Map: {"dataType": "Map", "value": [...]}."""
    if isinstance(value, dict):
        if value.get('dataType') == 'Map' and isinstance(value.get('value'), list):
            value = value['value']
        else:
            # An ordinary object
            return list(value.items())

    if not isinstance(value, list):
        return []

    return [
        (entry[0], entry[1])
        for entry in value
        if isinstance(entry, (list, tuple)) and len(entry) == 2
    ]


def load(content: bytes) -> dict | None:
    """The project in a file, or None if the file is not a project which can be read."""
    if not content or len(content) > READ_LIMIT:
        return None

    document = _load_json(content)

    if document is None and content[:2] == b'PK':
        # Some project formats are a zip archive around the same document
        document = _load_zip(content)

    if not isinstance(document, dict) or not isinstance(document.get('canvas'), list):
        return None

    return document


def _load_json(content: bytes):
    try:
        return json.loads(content.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


def _load_zip(content: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist()[:50]:
                if info.is_dir() or info.file_size > READ_LIMIT:
                    continue

                document = _load_json(archive.read(info))

                if isinstance(document, dict) and isinstance(document.get('canvas'), list):
                    return document
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
        pass

    return None


def _iso(milliseconds) -> str | None:
    value = _number(milliseconds)

    if value is None or value <= 0:
        return None

    try:
        moment = datetime.datetime.fromtimestamp(value / 1000, tz=datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None

    return moment.isoformat(timespec='seconds')


def _settings_of(shape: dict, operation: str) -> dict:
    """Power, speed and passes of a shape for the way it is processed."""
    data = shape.get('data')
    entry = data.get(operation) if isinstance(data, dict) else None

    if not isinstance(entry, dict):
        return {}

    parameter = entry.get('parameter')

    if not isinstance(parameter, dict):
        return {}

    # 'materialType' names the set in use: the user's own values ("customize")
    # or the ones xTool supplies for the material ("official")
    chosen = None

    for key in (entry.get('materialType'), entry.get('planType'), 'customize', 'official'):
        if isinstance(key, str) and isinstance(parameter.get(key), dict):
            chosen = parameter[key]
            break

    if chosen is None:
        chosen = next((value for value in parameter.values() if isinstance(value, dict)), None)

    if chosen is None:
        return {}

    return {
        'power': _number(chosen.get('power')),
        'speed': _number(chosen.get('speed')),
        'passes': _number(chosen.get('repeat')),
        'source': _text(chosen.get('processingLightSource'), 20),
    }


def _material_name(document: dict, material) -> str | None:
    device = document.get('device')
    materials = device.get('materialList') if isinstance(device, dict) else None

    if not isinstance(materials, list):
        return None

    for entry in materials:
        if not isinstance(entry, dict) or entry.get('id') != material:
            continue

        name = entry.get('name')

        if isinstance(name, dict):
            name = name.get('en') or next(
                (value for value in name.values() if isinstance(value, str) and value.strip()),
                None,
            )

        return _text(name)

    return None


def summarise(content: bytes, filename: str | None = None) -> dict:
    """What a project file is and what it does, for display.

    Sizes are in millimetres. 'width' and 'height' are the area which the
    processed shapes cover, without their rotation.
    """
    result = {
        'recognised': False,
        'project': is_project_name(filename),
        'size': len(content or b''),
    }

    try:
        document = load(content)

        if document is None:
            return result

        result.update(_summary(document))
        result['recognised'] = True
    except Exception:  # noqa: BLE001 - a summary is never worth an error
        return {
            'recognised': False,
            'project': is_project_name(filename),
            'size': len(content or b''),
        }

    return result


def _summary(document: dict) -> dict:
    device = document.get('device') if isinstance(document.get('device'), dict) else {}
    canvases = [canvas for canvas in document['canvas'] if isinstance(canvas, dict)]

    canvas = next(
        (entry for entry in canvases if entry.get('id') == document.get('canvasId')),
        canvases[0] if canvases else {},
    )

    settings = {}

    for key, value in _map_entries(device.get('data')):
        if key == canvas.get('id') and isinstance(value, dict):
            settings = value
            break

    per_shape = {
        key: value
        for key, value in _map_entries(settings.get('displays'))
        if isinstance(value, dict)
    }

    shapes = canvas.get('displays') if isinstance(canvas.get('displays'), list) else []

    groups: dict = {}
    box = None
    processed = 0
    skipped = 0

    for shape in shapes:
        if not isinstance(shape, dict):
            continue

        how = per_shape.get(shape.get('id'), {})

        if shape.get('visible') is False or how.get('processIgnore') is True:
            skipped += 1
            continue

        processed += 1

        x, y = _number(shape.get('x')), _number(shape.get('y'))
        width, height = _number(shape.get('width')), _number(shape.get('height'))

        if None not in (x, y, width, height):
            edges = (x, y, x + abs(width), y + abs(height))
            box = edges if box is None else (
                min(box[0], edges[0]),
                min(box[1], edges[1]),
                max(box[2], edges[2]),
                max(box[3], edges[3]),
            )

        operation = how.get('processingType')

        if not isinstance(operation, str) or not operation:
            continue

        values = _settings_of(how, operation)
        key = (operation, values.get('power'), values.get('speed'), values.get('passes'))

        if key not in groups:
            groups[key] = {
                'type': operation,
                'label': OPERATIONS.get(operation, operation.replace('_', ' ').capitalize()),
                'count': 0,
                'power': values.get('power'),
                'speed': values.get('speed'),
                'passes': values.get('passes'),
                'source': values.get('source'),
            }

        groups[key]['count'] += 1

    def order(group):
        position = _ORDER.index(group['type']) if group['type'] in _ORDER else len(_ORDER)
        return (position, -group['count'])

    operations = sorted(groups.values(), key=order)

    mode = _text(settings.get('mode'), 40)
    mode_data = settings.get('data') if isinstance(settings.get('data'), dict) else {}
    plane = mode_data.get(mode) if isinstance(mode_data.get(mode), dict) else {}

    cover = document.get('cover')

    return {
        'machine': _text(device.get('id')) or _text(document.get('extName')) or _text(document.get('extId')),
        'app_version': _text(document.get('version'), 30),
        'modified': _iso(document.get('modify')) or _iso(document.get('created')),
        'canvases': len(canvases),
        'canvas_title': _text(canvas.get('title'), 60),
        'shapes': processed,
        'skipped': skipped,
        'width': round(box[2] - box[0], 2) if box else None,
        'height': round(box[3] - box[1], 2) if box else None,
        'operations': operations,
        'cut_shapes': sum(
            group['count'] for group in operations if group['type'] == 'VECTOR_CUTTING'
        ),
        'mode': mode,
        'material': _material_name(document, plane.get('material')),
        'thickness': _number(plane.get('thickness')),
        'has_cover': isinstance(cover, str) and cover.startswith('data:image/'),
    }


def cover(content: bytes) -> tuple[bytes, str] | None:
    """The preview picture stored in a project file: (bytes, content type)."""
    document = load(content)
    value = document.get('cover') if document else None

    if not isinstance(value, str) or not value.startswith('data:'):
        return None

    header, _, encoded = value.partition(',')
    content_type = header[5:].split(';')[0].strip().lower()

    # Only pictures a browser shows as a picture: never SVG or HTML
    if content_type not in _IMAGE_TYPES or ';base64' not in header:
        return None

    if len(encoded) > COVER_LIMIT * 4 // 3 + 4:
        return None

    try:
        picture = base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError):
        return None

    if not picture or len(picture) > COVER_LIMIT:
        return None

    return picture, content_type
