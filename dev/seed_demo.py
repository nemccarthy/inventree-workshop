"""Fill a throwaway InvenTree with made-up data, for screenshots.

    python dev/seed_demo.py --inventree http://127.0.0.1:8000 --token inv-...

Creates a laser and a CNC mill, five in-house parts of an "Outdoor Sensor
Node" linked to files made by make_xcs.py and make_gcode.py, and jobs in
different states. Never run this against a real system.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from make_gcode import build as make_gcode  # noqa: E402
from make_xcs import build as make_xcs  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventree', default='http://127.0.0.1:8000')
    parser.add_argument('--token', required=True)
    args = parser.parse_args()

    headers = {'Authorization': f'Token {args.token}'}
    plugin = '/plugin/workshop'

    def it(method, path, data=None, files=None):
        response = requests.request(
            method, f'{args.inventree}{path}', headers=headers, json=data, files=files, timeout=60
        )

        if response.status_code >= 400:
            raise SystemExit(f'{method} {path}: {response.status_code} {response.text[:300]}')

        return response.json() if response.content else None

    laser = it('POST', f'{plugin}/machines/', {'name': 'xTool S1', 'kind': 'laser', 'notes': ''})['machine']
    mill = it(
        'POST',
        f'{plugin}/machines/',
        {
            'name': 'Makera Carvera',
            'kind': 'cnc',
            'notes': 'Tool 1: 3.175 mm flat end mill. Tool 3: 2 mm drill. Check the collet is clean.',
        },
    )['machine']

    category = it('POST', '/api/part/category/', {'name': 'Made in-house'})
    materials = it('POST', '/api/part/category/', {'name': 'Sheet and plate'})
    workshop = it('POST', '/api/stock/location/', {'name': 'Workshop'})
    bins = it('POST', '/api/stock/location/', {'name': 'Finished parts', 'parent': workshop['pk']})
    rack = it('POST', '/api/stock/location/', {'name': 'Material rack', 'parent': workshop['pk']})

    def part(name, ipn, description, **fields):
        return it(
            'POST',
            '/api/part/',
            {
                'name': name,
                'IPN': ipn,
                'description': description,
                'category': category['pk'],
                'component': True,
                'active': True,
                'default_location': bins['pk'],
                **fields,
            },
        )

    def material(name, ipn, description, quantity):
        made = part(
            name, ipn, description,
            category=materials['pk'], purchaseable=True, default_location=rack['pk'], units='',
        )
        it('POST', '/api/stock/', {'part': made['pk'], 'quantity': quantity, 'location': rack['pk']})

        return made

    sheet = material('Adhesive sheet A4', 'SM-001', 'Double sided adhesive, 1.1 mm, A4 sheet', 25)
    film = material('Clear film A4', 'SM-002', 'Polycarbonate film, 0.25 mm, A4 sheet', 12)
    blank = material('Aluminium plate 80 x 60 x 6', 'SM-010', '6061 plate, sawn blank', 14)

    pad = part('Adhesive pad', 'LC-001', 'Pad which holds the sensor board in the housing', minimum_stock=40)
    gasket = part('Gasket ring', 'LC-002', 'Seal between cap and housing', minimum_stock=12)
    window = part('Window film', 'LC-003', 'Clear window over the light sensor')
    plate = part('Mounting plate', 'CN-001', 'Plate which carries the sensor on the pole bracket', minimum_stock=6)
    bracket = part('Heat sink bracket', 'CN-002', 'Clamp for the heat sink', minimum_stock=8)

    def attach(target, name, content):
        return it(
            'POST', f"{plugin}/part/{target['pk']}/files/", files={'file': (name, content)}
        )['file']['attachment']

    def link(target, machine, files, per_run, **fields):
        it(
            'PUT',
            f"{plugin}/part/{target['pk']}/",
            {'machine': machine['id'], 'files': files, 'parts_per_run': per_run, **fields},
        )

    link(
        pad, laser, [attach(pad, 'adhesive-pad_x20_S1.xcs', make_xcs(5, 4))], 20,
        restock_to=100, run_minutes=6,
        setup_notes='Sheet against the top left stops of the jig, liner side down. Focus on the sheet, not the jig.',
    )
    link(gasket, laser, [attach(gasket, 'gasket-ring_x6_S1.xcs', make_xcs(3, 2))], 6, run_minutes=4)
    link(
        window, laser, [attach(window, 'window-film_x8_S1.xcs', make_xcs(4, 2))], 8,
        setup_notes='Peel the protective film only after cutting.',
    )
    link(
        plate,
        mill,
        [
            {'attachment': attach(plate, 'mounting-plate_side-a.nc', make_gcode(60, 40, 6, header=True, minutes=24)), 'label': 'Side A'},
            {'attachment': attach(plate, 'mounting-plate_side-b.nc', make_gcode(60, 40, 2, holes=False, header=True, minutes=9)), 'label': 'Side B'},
            {'attachment': attach(plate, 'mounting-plate_fixture.pdf', b'%PDF-1.4 made-up drawing'), 'label': 'Fixture'},
        ],
        1,
        run_minutes=40,
        setup_notes='Blank in the vise against the left stop. Probe the top after flipping to side B.',
    )
    link(
        bracket, mill,
        [attach(bracket, 'heat-sink-bracket_x2.nc', make_gcode(46, 18, 5, header=True, minutes=17))],
        2, run_minutes=20,
    )

    # What the parts are made from (a part is an assembly once it is linked)
    it('POST', '/api/bom/', {'part': pad['pk'], 'sub_part': sheet['pk'], 'quantity': 0.05})
    it('POST', '/api/bom/', {'part': window['pk'], 'sub_part': film['pk'], 'quantity': 0.125})
    it('POST', '/api/bom/', {'part': plate['pk'], 'sub_part': blank['pk'], 'quantity': 1})

    it('POST', '/api/stock/', {'part': gasket['pk'], 'quantity': 30, 'location': bins['pk']})
    it('POST', '/api/stock/', {'part': bracket['pk'], 'quantity': 3, 'location': bins['pk']})

    def job(target, runs, notes=''):
        return it('POST', f"{plugin}/part/{target['pk']}/make/", {'runs': runs, 'notes': notes})['job']

    def book(build, **data):
        return it('POST', f'{plugin}/job/{build}/book/', data)

    # Finished: one closed short, two complete
    first = job(pad, 2)
    book(first['build'], good=18, runs=1)
    book(first['build'], good=20, runs=1, finish=True)

    done = job(gasket, 1)
    book(done['build'], good=6, runs=1)

    plates = job(plate, 2)
    book(plates['build'], good=2, runs=2)

    # Part made: one sheet of windows done, one to go
    half = job(window, 2)
    book(half['build'], good=7, runs=1, notes='One window scratched')

    # To make
    job(plate, 4, notes='For the next batch of nodes')
    job(gasket, 2)

    # Needs making: a build order in production which uses pads, gaskets and plates
    node = it(
        'POST',
        '/api/part/',
        {
            'name': 'Outdoor Sensor Node',
            'IPN': 'OSN-100',
            'description': 'Finished unit',
            'category': category['pk'],
            'assembly': True,
            'active': True,
        },
    )
    it('POST', '/api/bom/', {'part': node['pk'], 'sub_part': pad['pk'], 'quantity': 2})
    it('POST', '/api/bom/', {'part': node['pk'], 'sub_part': gasket['pk'], 'quantity': 1})
    it('POST', '/api/bom/', {'part': node['pk'], 'sub_part': plate['pk'], 'quantity': 1})

    order = it('POST', '/api/build/', {'part': node['pk'], 'quantity': 30})
    it('POST', f"/api/build/{order['pk']}/issue/", {})

    print('Seeded. Adhesive pad is part', pad['pk'], 'and Mounting plate is part', plate['pk'])


if __name__ == '__main__':
    main()
