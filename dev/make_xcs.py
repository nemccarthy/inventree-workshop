"""Make a small xTool project file (.xcs) with made-up content, for tests and screenshots.

    python dev/make_xcs.py pads.xcs --columns 5 --rows 4 --width 18 --height 12

The file has the structure which xTool Creative Space and xTool Studio write
(see inventree_xtool/xcs.py): a grid of rectangles set to cut, an outline set
to score, and a preview picture. It is only meant for this plugin to read: it
has not been opened in xTool Studio.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import uuid
import zlib


def png(width: int, height: int, boxes: list[tuple], scale: float) -> bytes:
    """A tiny greyscale picture of the layout: boxes drawn as outlines."""
    rows = [bytearray(b'\xff' * width) for _ in range(height)]

    for x, y, w, h in boxes:
        left, top = int(x * scale), int(y * scale)
        right, bottom = min(width - 1, int((x + w) * scale)), min(height - 1, int((y + h) * scale))

        for column in range(left, right + 1):
            rows[top][column] = rows[bottom][column] = 0x30

        for row in range(top, bottom + 1):
            rows[row][left] = rows[row][right] = 0x30

    raw = b''.join(b'\x00' + bytes(row) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b'')
    )


def shape(kind: str, x: float, y: float, width: float, height: float) -> dict:
    return {
        'id': str(uuid.uuid4()),
        'name': None,
        'type': kind,
        'x': x,
        'y': y,
        'angle': 0,
        'scale': {'x': 1, 'y': 1},
        'offsetX': x,
        'offsetY': y,
        'width': width,
        'height': height,
        'isFill': False,
        'layerTag': '#2366ff',
        'layerColor': '#2366ff',
        'visible': True,
    }


def processing(kind: str, operation: str, power: int, speed: int, passes: int = 1) -> dict:
    values = {
        'processingLightSource': 'blue',
        'power': power,
        'speed': speed,
        'repeat': passes,
    }

    return {
        'isFill': False,
        'type': kind,
        'processingType': operation,
        'data': {operation: {'materialType': 'customize', 'parameter': {'customize': values}}},
        'processIgnore': False,
    }


def build(
    columns: int = 5,
    rows: int = 4,
    width: float = 18.0,
    height: float = 12.0,
    gap: float = 3.0,
    machine: str = 'S1',
    power: int = 35,
    speed: int = 60,
) -> bytes:
    """The content of a project file with a grid of pads to cut."""
    canvas_id = str(uuid.uuid4())
    margin = 5.0
    shapes = []
    settings = []
    boxes = []

    for row in range(rows):
        for column in range(columns):
            x = margin + column * (width + gap)
            y = margin + row * (height + gap)
            pad = shape('RECT', x, y, width, height)
            shapes.append(pad)
            settings.append([pad['id'], processing('RECT', 'VECTOR_CUTTING', power, speed)])
            boxes.append((x, y, width, height))

    sheet_width = 2 * margin + columns * width + (columns - 1) * gap
    sheet_height = 2 * margin + rows * height + (rows - 1) * gap

    # The edge of the sheet, scored lightly as a guide for lining up
    outline = shape('RECT', 0, 0, sheet_width, sheet_height)
    shapes.append(outline)
    settings.append([outline['id'], processing('RECT', 'VECTOR_ENGRAVING', 8, 120)])
    boxes.append((0, 0, sheet_width, sheet_height))

    scale = 2.0
    picture = png(int(sheet_width * scale) + 2, int(sheet_height * scale) + 2, boxes, scale)

    document = {
        'canvasId': canvas_id,
        'canvas': [
            {
                'id': canvas_id,
                'title': '{panel}1',
                'layerData': {'#2366ff': {'name': '{layer} 1', 'order': 1, 'visible': True}},
                'groupData': {},
                'displays': shapes,
            }
        ],
        'extId': machine,
        'extName': machine,
        'device': {
            'id': machine,
            'power': 20,
            'data': {
                'dataType': 'Map',
                'value': [
                    [
                        canvas_id,
                        {
                            'mode': 'LASER_PLANE',
                            'data': {
                                'LASER_PLANE': {
                                    'material': 0,
                                    'thickness': 1.1,
                                    'pathPlanning': 'auto',
                                }
                            },
                            'displays': {'dataType': 'Map', 'value': settings},
                        },
                    ]
                ],
            },
            'materialList': [],
            'materialTypeList': [],
        },
        'version': '2.2.23',
        'created': 1763600000000,
        'modify': 1763600000000,
        'cover': 'data:image/png;base64,' + base64.b64encode(picture).decode('ascii'),
        'minRequiredVersion': '',
    }

    return json.dumps(document, separators=(',', ':')).encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('output')
    parser.add_argument('--columns', type=int, default=5)
    parser.add_argument('--rows', type=int, default=4)
    parser.add_argument('--width', type=float, default=18.0)
    parser.add_argument('--height', type=float, default=12.0)
    parser.add_argument('--machine', default='S1')
    args = parser.parse_args()

    content = build(args.columns, args.rows, args.width, args.height, machine=args.machine)

    with open(args.output, 'wb') as handle:
        handle.write(content)

    print(f'{args.output}: {len(content)} bytes, {args.columns * args.rows} pads')


if __name__ == '__main__':
    main()
