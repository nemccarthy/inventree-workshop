"""Make a small G-code program with made-up content, for tests and screenshots.

    python dev/make_gcode.py bracket.nc --width 60 --height 40 --depth 6

The program mills the outline of a rectangle in passes with one tool, then
drills four holes with another. It is only meant for this plugin to read: do
not run it on a machine.
"""

from __future__ import annotations

import argparse


def build(
    width: float = 60.0,
    height: float = 40.0,
    depth: float = 6.0,
    step: float = 1.5,
    spindle: int = 12000,
    feed: int = 600,
    holes: bool = True,
    header: bool = False,
    minutes: int = 24,
) -> bytes:
    """The content of a program which cuts out a plate.

    With 'header' it starts with the kind of header Makera's CAM software
    writes: machine, material, stock, tools and running time.
    """
    lines = []

    if header:
        lines += [
            ';@MKR|BEGIN',
            ';@MKR|SCHEMA|v=1.0.0',
            ';@MKR|MACHINE|id=C1|name=Makera Carvera',
            f';@MKR|MATERIAL|id=0|name=Aluminium plate {depth:g} mm',
            f';@MKR|STOCK|id=cuboid|length={width + 20:g}|width={height + 20:g}|height={depth:g}|diameter=1',
            ';@MKR|UNIT|value=MM',
            ';@MKR|TOOL|number=1|id=1|name=3.175 mm flat end mill|type=Flat End|diameter=3.175',
        ]

        if holes:
            lines.append(';@MKR|TOOL|number=3|id=3|name=2 mm drill|type=Drill|diameter=2')

        lines += [
            f';@MKR|TIME|seconds={minutes * 60}',
            ';@MKR|TOOLPATH|number=1|tool_number=1|name=[T1]2D Contour',
            ';@MKR|END',
            '',
        ]

    lines += [
        '(Made-up program: do not run)',
        'G90 G21 G17',
        'M6 T1',
        f'M3 S{spindle}',
        'G0 Z5',
        'G0 X0 Y0',
    ]

    z = 0.0

    while z < depth:
        z = min(depth, z + step)
        lines += [
            f'G1 Z-{z:g} F{feed // 3}',
            f'G1 X{width:g} F{feed}',
            f'G1 Y{height:g}',
            'G1 X0',
            'G1 Y0',
        ]

    lines.append('G0 Z5')

    if holes:
        lines += ['M5', 'M6 T3', f'M3 S{spindle - 2000}']

        for x, y in ((6, 6), (width - 6, 6), (width - 6, height - 6), (6, height - 6)):
            lines += [f'G0 X{x:g} Y{y:g}', f'G1 Z-{depth:g} F{feed // 4}', 'G0 Z5']

    lines += ['M5', 'G28', 'M30', '']

    return '\n'.join(lines).encode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('output')
    parser.add_argument('--width', type=float, default=60.0)
    parser.add_argument('--height', type=float, default=40.0)
    parser.add_argument('--depth', type=float, default=6.0)
    args = parser.parse_args()

    content = build(args.width, args.height, args.depth)

    with open(args.output, 'wb') as handle:
        handle.write(content)

    print(f'{args.output}: {len(content)} bytes')


if __name__ == '__main__':
    main()
