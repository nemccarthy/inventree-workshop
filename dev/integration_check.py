"""End-to-end check of the plugin against a live InvenTree.

For a throwaway test setup only: it creates machines, parts, stock,
attachments, build orders and users.

    python dev/integration_check.py --inventree http://127.0.0.1:8000 --token inv-...
"""

from __future__ import annotations

import argparse
import hashlib
import io
import pathlib
import sys
import time
import zipfile

import requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from make_gcode import build as make_gcode  # noqa: E402
from make_xcs import build as make_xcs  # noqa: E402

PASSED = 0
FAILED = []


def check(name: str, condition, detail=''):
    global PASSED

    if condition:
        PASSED += 1
        print(f'  ok    {name}')
    else:
        FAILED.append(name)
        print(f'  FAIL  {name}  {detail}')


class Api:
    def __init__(self, base: str, headers: dict):
        self.base = base.rstrip('/')
        self.headers = headers

    def call(self, method: str, path: str, expect=None, **kwargs):
        response = requests.request(
            method, f'{self.base}{path}', headers=self.headers, timeout=60, **kwargs
        )

        if expect is not None and response.status_code != expect:
            raise AssertionError(f'{method} {path}: {response.status_code} {response.text[:400]}')

        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None

    def raw(self, path: str):
        return requests.get(f'{self.base}{path}', headers=self.headers, timeout=60)

    def get(self, path, **kwargs):
        return self.call('GET', path, **kwargs)[1]

    def post(self, path, data=None, **kwargs):
        return self.call('POST', path, json=data or {}, **kwargs)[1]

    def put(self, path, data=None, **kwargs):
        return self.call('PUT', path, json=data or {}, **kwargs)[1]

    def patch(self, path, data=None, **kwargs):
        return self.call('PATCH', path, json=data or {}, **kwargs)[1]

    def upload(self, path, name: str, content: bytes, expect=None):
        return self.call('POST', path, expect=expect, files={'file': (name, content)})


def wait_for(condition, seconds=40, step=1):
    deadline = time.time() + seconds

    while time.time() < deadline:
        value = condition()

        if value:
            return value

        time.sleep(step)

    return None


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventree', default='http://127.0.0.1:8000')
    parser.add_argument('--token', required=True)
    args = parser.parse_args()

    it = Api(args.inventree, {'Authorization': f'Token {args.token}'})
    plugin = '/plugin/workshop'
    tag = str(int(time.time()))[-6:]

    def stock_of(part: int) -> float:
        return float(it.get(f'/api/part/{part}/', expect=200)['total_in_stock'] or 0)

    def build_of(pk: int) -> dict:
        return it.get(f'/api/build/{pk}/', expect=200)

    def rows(value):
        return value['results'] if isinstance(value, dict) else value

    # ---- data

    category = it.post('/api/part/category/', {'name': f'Workshop check {tag}'}, expect=201)
    shelf = it.post('/api/stock/location/', {'name': f'Workshop shelf {tag}'}, expect=201)
    other_shelf = it.post('/api/stock/location/', {'name': f'Other shelf {tag}'}, expect=201)

    def new_part(name, **fields):
        return it.post(
            '/api/part/',
            {
                'name': f'{name} {tag}',
                'description': 'Made-up part for the plugin check',
                'category': category['pk'],
                'component': True,
                'active': True,
                **fields,
            },
            expect=201,
        )

    pad = new_part('Adhesive pad', minimum_stock=40, default_location=shelf['pk'])
    sheet = new_part('Adhesive sheet', purchaseable=True, units='')
    liner = new_part('Backing liner', purchaseable=True)
    plate = new_part('Mounting plate')
    plain = new_part('Gasket')
    serialised = new_part('Tracked plate', trackable=True)
    housing = new_part('Housing', assembly=True)

    it.post('/api/bom/', {'part': housing['pk'], 'sub_part': pad['pk'], 'quantity': 2}, expect=201)

    it.post('/api/stock/', {'part': sheet['pk'], 'quantity': 4, 'location': other_shelf['pk']}, expect=201)
    it.post('/api/stock/', {'part': sheet['pk'], 'quantity': 6, 'location': shelf['pk']}, expect=201)
    it.post('/api/stock/', {'part': liner['pk'], 'quantity': 50, 'location': shelf['pk']}, expect=201)

    project = make_xcs(5, 4)
    side_a = make_gcode(60, 40, 6, header=True, minutes=24)
    side_b = make_gcode(60, 40, 2, holes=False)

    print('\nMachines')

    code, body = it.call('POST', f'{plugin}/machines/', json={'name': f'  Laser  {tag} ', 'kind': 'laser', 'notes': 'By the window'})
    check('a machine can be added', code == 201 and body['machine']['name'] == f'Laser {tag}' and body['machine']['kind'] == 'laser', body)
    laser = body['machine']
    code, body = it.call('POST', f'{plugin}/machines/', json={'name': f'Mill {tag}', 'kind': 'cnc'})
    mill = body['machine']
    check('a second machine gets its own id', code == 201 and mill['id'] != laser['id'])
    code, body = it.call('POST', f'{plugin}/machines/', json={'name': f'laser {tag}'.upper(), 'kind': 'laser'})
    check('two machines cannot have the same name', code == 400 and 'name' in body.get('errors', {}), body)
    code, body = it.call('POST', f'{plugin}/machines/', json={'name': '', 'kind': 'lathe'})
    check('a machine needs a name and a known kind', code == 400 and {'name', 'kind'} <= set(body.get('errors', {})), body)
    code, body = it.call('PUT', f"{plugin}/machines/{mill['id']}/", json={'name': f'CNC mill {tag}', 'kind': 'cnc', 'notes': 'Tool 1 is the 3 mm end mill'})
    check('a machine can be renamed', code == 200 and body['machine']['name'] == f'CNC mill {tag}' and body['machine']['id'] == mill['id'], body)
    mill = body['machine']
    code, body = it.call('PUT', f'{plugin}/machines/99999/', json={'name': 'x', 'kind': 'cnc'})
    check('an unknown machine is not found', code == 404, code)
    spare = it.post(f'{plugin}/machines/', {'name': f'Spare {tag}', 'kind': 'other'}, expect=201)['machine']
    code, body = it.call('DELETE', f"{plugin}/machines/{spare['id']}/")
    check('an unused machine can be removed', code == 200 and all(m['id'] != spare['id'] for m in body['machines']), body)
    listed = {m['id']: m for m in it.get(f'{plugin}/machines/', expect=200)['machines']}
    check('the machines are listed with their kind', listed[laser['id']]['kind_name'] == 'Laser' and listed[mill['id']]['kind_name'] == 'CNC' and listed[mill['id']]['parts'] == 0)

    print('\nFiles')

    code, body = it.upload(f"{plugin}/part/{pad['pk']}/files/", 'pad_x20.xcs', project)
    check('a file can be attached to a part', code == 201, f'{code} {body}')
    file = body['file']
    summary = file['summary']
    check('an xTool project is recognised', summary['recognised'] and summary['kind'] == 'xcs')
    check('the hash of the stored file is that of the upload', file['file_hash'] == sha(project))
    check('20 shapes are set to cut', summary['parts_hint'] == 20, summary)
    check(
        'the settings of the cut are read',
        summary['operations'][0] == {'label': 'Cut × 20', 'detail': '35% · 60 mm/s', 'tone': 'cut'},
        summary['operations'],
    )
    check('the machine and the area are read', summary['facts'][:2] == ['xTool S1', '112 × 67 mm'], summary['facts'])

    code, body = it.upload(f"{plugin}/part/{plate['pk']}/files/", 'plate_side-a.nc', side_a, expect=201)
    nc_a = body['file']
    check('a G-code program is recognised', nc_a['summary']['recognised'] and nc_a['summary']['kind'] == 'gcode')
    check(
        'its travel, tools and running time are read',
        '60 × 40 mm, 6 mm deep' in nc_a['summary']['facts']
        and nc_a['summary']['operations'][0] == {'label': 'Tool 1', 'detail': '3.175 mm flat end mill', 'tone': 'other'}
        and nc_a['summary']['minutes_hint'] == 24,
        nc_a['summary'],
    )
    nc_b = it.upload(f"{plugin}/part/{plate['pk']}/files/", 'plate_side-b.nc', side_b, expect=201)[1]['file']
    drawing = it.upload(f"{plugin}/part/{plate['pk']}/files/", 'fixture.pdf', b'%PDF-1.7 made up', expect=201)[1]['file']
    check('any other file is stored, without details', not drawing['summary']['recognised'] and drawing['summary']['kind'] == '')

    listing = it.get(f"{plugin}/part/{plate['pk']}/files/", expect=200)['files']
    check(
        'the attachments are listed with their kind, newest first',
        [(entry['attachment'], entry['kind']) for entry in listing]
        == [(drawing['attachment'], ''), (nc_b['attachment'], 'gcode'), (nc_a['attachment'], 'gcode')],
        listing,
    )
    native = rows(it.get(f"/api/attachment/?model_type=part&model_id={pad['pk']}", expect=200))
    check('they are ordinary InvenTree attachments of the part', len(native) == 1 and native[0]['pk'] == file['attachment'])

    code, body = it.upload(f"{plugin}/part/{pad['pk']}/files/", 'broken.xcs', b'{"canvas": 3, ')
    check('a damaged project file is stored without details', code == 201 and not body['file']['summary']['recognised'])
    code, body = it.call('POST', f"{plugin}/part/{pad['pk']}/files/")
    check('an upload without a file is refused', code == 400, code)

    print('\nLinking')

    def link_body(**changes):
        data = {'machine': laser['id'], 'files': [{'attachment': file['attachment']}], 'parts_per_run': 20}
        data.update(changes)
        return data

    put = f"{plugin}/part/{pad['pk']}/"

    code, body = it.call('PUT', put, json=link_body(parts_per_run=0))
    check('zero parts per run is refused', code == 400 and 'parts_per_run' in body.get('errors', {}), body)
    code, body = it.call('PUT', put, json=link_body(machine=99999))
    check('an unknown machine is refused', code == 400 and 'machine' in body.get('errors', {}), body)
    code, body = it.call('PUT', put, json=link_body(files=[]))
    check('a link needs a file', code == 400 and 'files' in body.get('errors', {}), body)
    code, body = it.call('PUT', put, json=link_body(files=[{'attachment': 99999999}]))
    check('a file which is not attached is refused', code == 400 and 'files' in body.get('errors', {}), body)
    code, body = it.call('PUT', put, json=link_body(files=[{'attachment': nc_a['attachment']}]))
    check('the file of another part is refused', code == 400 and 'files' in body.get('errors', {}), body)
    code, body = it.call('PUT', put, json=link_body(files=[{'attachment': file['attachment']}, {'attachment': file['attachment']}]))
    check('the same file twice is refused', code == 400 and 'twice' in body['detail'], body)
    code, body = it.call('PUT', f"{plugin}/part/{serialised['pk']}/", json=link_body())
    check('a serialised part is refused', code == 400 and 'serial' in body['detail'], body)
    code, body = it.call('PUT', put, json=link_body(restock_to='lots', destination=99999999, run_minutes=-5))
    check(
        'wrong numbers and a wrong location are all reported',
        code == 400 and {'restock_to', 'destination', 'run_minutes'} <= set(body.get('errors', {})),
        body,
    )

    code, body = it.call('PUT', put, json=link_body(setup_notes='Sheet against the top left corner of the jig.'))
    check('the part is linked', code == 200 and body['link']['parts_per_run'] == 20 and body['link']['machine_name'] == laser['name'], body)
    check('linking makes the part an assembly', body.get('made_assembly') is True and it.get(f"/api/part/{pad['pk']}/")['assembly'])
    check('the link keeps what the file says about itself', body['link']['files'][0]['summary']['parts_hint'] == 20)

    # A bill of materials can be added once the part is an assembly
    it.post('/api/bom/', {'part': pad['pk'], 'sub_part': sheet['pk'], 'quantity': 0.05}, expect=201)
    it.post('/api/bom/', {'part': pad['pk'], 'sub_part': liner['pk'], 'quantity': 0.05, 'consumable': True}, expect=201)

    part_data = it.get(put, expect=200)
    check(
        'the bill of materials is shown: one taken from stock, one consumable',
        [(m['part'], m['taken']) for m in part_data['materials']] == [(sheet['pk'], True), (liner['pk'], False)],
        part_data['materials'],
    )
    check('the linked file is in place', not part_data['link']['file_missing'] and not part_data['link']['file_changed'])
    check(
        'with no stock and a minimum of 40, two runs are suggested',
        part_data['suggestion']['runs'] == 2 and part_data['suggestion']['reason'] == 'low_stock',
        part_data['suggestion'],
    )

    response = it.raw(f"{plugin}/part/{pad['pk']}/download/")
    check(
        'a single linked file downloads as itself, unchanged',
        response.status_code == 200
        and sha(response.content) == sha(project)
        and 'pad_x20' in response.headers.get('Content-Disposition', ''),
        response.headers,
    )
    response = it.raw(f"{plugin}/part/{pad['pk']}/preview/")
    check(
        'the preview picture is served as a picture',
        response.status_code == 200 and response.headers['Content-Type'] == 'image/png' and response.content.startswith(b'\x89PNG'),
        response.status_code,
    )
    response = it.raw(f"{plugin}/part/{plate['pk']}/preview/?attachment={nc_a['attachment']}")
    check('a file without a picture has no preview', response.status_code == 404, response.status_code)
    response = it.raw(f"{plugin}/part/{plain['pk']}/download/")
    check('a part without a link has nothing to download', response.status_code == 404, response.status_code)

    print('\nA part with several files')

    plate_put = f"{plugin}/part/{plate['pk']}/"
    code, body = it.call(
        'PUT',
        plate_put,
        json={
            'machine': mill['id'],
            'files': [
                {'attachment': nc_a['attachment'], 'label': 'Side A'},
                {'attachment': nc_b['attachment'], 'label': 'Side B'},
                {'attachment': drawing['attachment'], 'label': 'Fixture'},
            ],
            'parts_per_run': 2,
            'run_minutes': 30,
            'destination': other_shelf['pk'],
        },
    )
    check('a part is linked to three files on the mill', code == 200 and len(body['link']['files']) == 3 and body['link']['machine_kind'] == 'cnc', body)
    check(
        'the files keep their order and labels',
        [(entry['attachment'], entry['label']) for entry in body['link']['files']]
        == [(nc_a['attachment'], 'Side A'), (nc_b['attachment'], 'Side B'), (drawing['attachment'], 'Fixture')],
    )
    check('the machine time of a run is kept', body['link']['run_minutes'] == 30)
    check('the notes of the machine come with the link', body['link']['machine_notes'] == 'Tool 1 is the 3 mm end mill')

    response = it.raw(f"{plugin}/part/{plate['pk']}/download/")
    archive = zipfile.ZipFile(io.BytesIO(response.content)) if response.status_code == 200 else None
    check(
        'several files download as one zip, in order',
        archive is not None
        and response.headers['Content-Type'] == 'application/zip'
        and [name[:12] for name in archive.namelist()] == ['plate_side-a', 'plate_side-b', 'fixture.pdf'[:12]],
        archive.namelist() if archive else response.status_code,
    )
    check(
        'the files in the zip are unchanged',
        archive is not None
        and sha(archive.read(archive.namelist()[0])) == sha(side_a)
        and sha(archive.read(archive.namelist()[1])) == sha(side_b),
    )
    response = it.raw(f"{plugin}/part/{plate['pk']}/file/{nc_b['attachment']}/")
    check('one file of the part downloads by itself', response.status_code == 200 and sha(response.content) == sha(side_b))
    response = it.raw(f"{plugin}/part/{plate['pk']}/file/{file['attachment']}/")
    check('but not a file of another part', response.status_code == 404, response.status_code)

    code, body = it.call('DELETE', f"{plugin}/machines/{mill['id']}/")
    check('a machine with parts linked to it cannot be removed', code == 400 and '1 part is linked' in body['detail'], body)

    code, body = it.call('POST', f"{plugin}/part/{plate['pk']}/make/", json={'quantity': 5})
    check('a job for 5 plates is raised as three runs', code == 201 and body['job']['runs'] == 3 and body['job']['quantity'] == 6, body)
    plate_job = body['job']
    check('the build order is named after the machine', build_of(plate_job['build'])['title'] == f"CNC mill {tag}: 3 runs of Mounting plate {tag}", build_of(plate_job['build'])['title'])
    check(
        'the job records its machine, its files and the time of a run',
        plate_job['machine']['id'] == mill['id']
        and [entry['label'] for entry in plate_job['files']] == ['Side A', 'Side B', 'Fixture']
        and plate_job['files'][0]['file_hash'] == sha(side_a)
        and plate_job['run_minutes'] == 30,
        plate_job,
    )
    response = it.raw(f"{plugin}/job/{plate_job['build']}/download/")
    check('the files of the job download as a zip named after the build order', response.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(response.content)).namelist()) == 3 and build_of(plate_job['build'])['reference'] in response.headers.get('Content-Disposition', ''))
    response = it.raw(f"{plugin}/job/{plate_job['build']}/file/{nc_a['attachment']}/")
    check('one file of the job downloads by itself', response.status_code == 200 and sha(response.content) == sha(side_a))
    response = it.raw(f"{plugin}/job/{plate_job['build']}/file/{file['attachment']}/")
    check('but not a file which is not of the job', response.status_code == 404, response.status_code)

    it.put(f"{plugin}/machines/{mill['id']}/", {'name': f'Carvera {tag}', 'kind': 'cnc'}, expect=200)
    data = it.get(plate_put, expect=200)
    check('a renamed machine shows on the link', data['link']['machine_name'] == f'Carvera {tag}')
    check('the job keeps the name it was raised with', data['jobs'][0]['machine']['name'] == f'CNC mill {tag}')

    it.call('DELETE', f"/api/attachment/{nc_b['attachment']}/", expect=204)
    data = it.get(plate_put, expect=200)
    check(
        'a deleted attachment is noticed, file by file',
        data['link']['file_missing'] and [entry['missing'] for entry in data['link']['files']] == [False, True, False],
        data['link'],
    )
    code, body = it.call('POST', f"{plugin}/part/{plate['pk']}/make/", json={'runs': 1})
    check('and a job is refused, naming the file', code == 400 and 'plate_side-b' in body['detail'], body)
    response = it.raw(f"{plugin}/part/{plate['pk']}/download/")
    check('what is left still downloads', response.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(response.content)).namelist()) == 2)
    code, body = it.call('POST', f"{plugin}/job/{plate_job['build']}/book/", json={'good': 6, 'runs': 3})
    check('the open job can still be booked', code == 200 and body['result']['closed'] and stock_of(plate['pk']) == 6, body)
    placed = rows(it.get(f"/api/stock/?part={plate['pk']}&location={other_shelf['pk']}&in_stock=true", expect=200))
    check('its parts went to the location of the link', sum(float(i['quantity']) for i in placed) == 6, placed)

    print('\nA job')

    code, body = it.call('POST', f"{plugin}/part/{plain['pk']}/make/", json={'runs': 1})
    check('a part without a link cannot be made', code == 400, code)
    code, body = it.call('POST', f"{plugin}/part/{pad['pk']}/make/", json={'runs': 0})
    check('a job of zero runs is refused', code == 400, code)
    code, body = it.call('POST', f"{plugin}/part/{pad['pk']}/make/", json={'runs': 5000})
    check('a job of 5000 runs is refused', code == 400, code)

    code, body = it.call('POST', f"{plugin}/part/{pad['pk']}/make/", json={'quantity': 30, 'notes': 'For the check'})
    check('a job for 30 parts is raised as two runs', code == 201 and body['job']['runs'] == 2, body)
    job = body['job']
    build = build_of(job['build'])
    check(
        'it is a build order in production for 40 parts',
        float(build['quantity']) == 40 and build['status_text'] == 'Production' and build['part'] == pad['pk'],
        (build['quantity'], build['status_text']),
    )
    check('the parts go to the default location of the part', build['destination'] == shelf['pk'], build['destination'])
    check('the job is open', job['summary']['state'] == 'open' and job['summary']['runs_left'] == 2, job['summary'])
    check(
        'the material of the job is the sheet: one per run, ten in stock',
        len(job['material']) == 1
        and job['material'][0]['part'] == sheet['pk']
        and job['material'][0]['per_run'] == 1
        and job['material'][0]['in_stock'] == 10,
        job['material'],
    )
    check(
        'the open job counts as incoming, so nothing more is suggested',
        body['numbers']['incoming'] == 40 and body['suggestion']['runs'] == 0,
        (body['numbers'], body['suggestion']),
    )

    print('\nBooking')

    book = f"{plugin}/job/{job['build']}/book/"

    code, body = it.call('POST', book, json={'good': 25, 'runs': 1})
    check('more good parts than the runs can give is refused', code == 400 and 'Raise the number of runs' in body['detail'], body)
    code, body = it.call('POST', book, json={'good': 5, 'runs': 0})
    check('a booking without a run is refused', code == 400, body)
    code, body = it.call('POST', book, json={'good': 2.5, 'runs': 1})
    check('half a part is refused', code == 400, body)
    code, body = it.call('POST', book, json={'good': 18, 'runs': 1, 'material': [{'line': job['material'][0]['line'], 'quantity': 11}]})
    check('more material than there is in stock is refused', code == 400 and 'not enough' in body['detail'], body)
    code, body = it.call('POST', book, json={'good': 18, 'runs': 1, 'material': [{'line': 99999999, 'quantity': 1}]})
    check('material which is not on the build order is refused', code == 400, body)
    code, body = it.call('POST', book, json={'good': 18, 'runs': 1, 'material': [{'line': job['material'][0]['line'], 'quantity': -1}]})
    check('a negative quantity of material is refused', code == 400, body)
    check('a refused booking changes nothing', stock_of(pad['pk']) == 0 and stock_of(sheet['pk']) == 10 and float(build_of(job['build'])['completed']) == 0)

    code, body = it.call('POST', book, json={'good': 18, 'runs': 1})
    check('18 good parts of one run are booked', code == 200 and body['result']['good'] == 18, body)
    check('they are in stock', stock_of(pad['pk']) == 18, stock_of(pad['pk']))
    check('one sheet was taken from stock', stock_of(sheet['pk']) == 9 and body['result']['material'][0]['quantity'] == 1, stock_of(sheet['pk']))
    check('the consumable liner was not', stock_of(liner['pk']) == 50)

    items = rows(it.get(f"/api/stock/?part={sheet['pk']}&location={shelf['pk']}&in_stock=true", expect=200))
    check('the oldest stock was used first (the other shelf)', sum(float(i['quantity']) for i in items) == 6, items)

    lines = rows(it.get(f"/api/build/line/?build={job['build']}", expect=200))
    check('the build order shows the sheet as consumed', sorted(float(line['consumed']) for line in lines) == [0, 1], lines)

    made = rows(it.get(f"/api/stock/?part={pad['pk']}&in_stock=true", expect=200))[0]
    history = rows(it.get(f"/api/audit/?model_type=stockitem&model_id={made['pk']}", expect=200))
    check('the history of the stock names the machine', f'Made on Laser {tag}' in str(history), str(history)[:400])

    state = body['job']['summary']
    check(
        'the job is part made: 22 to go, two rejects, two runs left',
        state['state'] == 'partial' and state['remaining'] == 22 and state['rejected'] == 2 and state['runs_left'] == 2,
        state,
    )
    check('the booking is on record', body['job']['bookings'][0]['good'] == 18 and body['job']['bookings'][0]['by'] == 'admin')

    code, body = it.call(
        'POST',
        book,
        json={'good': 20, 'runs': 1, 'location': other_shelf['pk'], 'notes': 'second sheet', 'material': [{'line': job['material'][0]['line'], 'quantity': 1.5}]},
    )
    check('a second booking with its own material quantity', code == 200 and stock_of(sheet['pk']) == 7.5, stock_of(sheet['pk']))
    check('the job stays open, two short', body['job']['summary']['state'] == 'partial' and body['job']['summary']['remaining'] == 2)
    placed = rows(it.get(f"/api/stock/?part={pad['pk']}&location={other_shelf['pk']}&in_stock=true", expect=200))
    check('the parts went to the location which was chosen', sum(float(i['quantity']) for i in placed) == 20, placed)

    code, body = it.call('POST', f"{plugin}/job/{job['build']}/cancel/")
    check('a job with parts in stock cannot be cancelled', code == 400, body)

    code, body = it.call('POST', f"{plugin}/job/{job['build']}/close/")
    check('the job is closed short', code == 200 and body['result']['closed'] and body['job']['summary']['state'] == 'done', body)
    done = wait_for(lambda: build_of(job['build'])['status_text'] == 'Complete')
    check('the build order is complete with 38 parts', done and float(build_of(job['build'])['completed']) == 38)
    check('the job is in the history, not in the open jobs', not body['jobs'] and body['history'][0]['build'] == job['build'])

    code, body = it.call('POST', book, json={'good': 1, 'runs': 1})
    check('a closed job takes no more bookings', code == 400, body)

    print('\nOther ways a job ends')

    def new_job(runs=1, part=pad):
        return it.post(f"{plugin}/part/{part['pk']}/make/", {'runs': runs}, expect=201)['job']

    job = new_job()
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/close/")
    check('a job with nothing booked cannot be closed', code == 400, body)
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/cancel/")
    check('it can be cancelled', code == 200 and body['result']['build_cancelled'] and body['job']['summary']['state'] == 'cancelled', body)
    check('the build order is cancelled', wait_for(lambda: build_of(job['build'])['status_text'] == 'Cancelled'))

    job = new_job()
    before = stock_of(sheet['pk'])
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/book/", json={'good': 20, 'runs': 1, 'material': []})
    check('a full run completes the job by itself', code == 200 and body['result']['closed'] and body['job']['summary']['state'] == 'done', body)
    check('an empty material list still uses what the bill of materials says', stock_of(sheet['pk']) == before - 1, stock_of(sheet['pk']))

    job = new_job()
    before = stock_of(sheet['pk'])
    code, body = it.call(
        'POST',
        f"{plugin}/job/{job['build']}/book/",
        json={'good': 0, 'runs': 1, 'finish': True, 'material': [{'line': job['material'][0]['line'], 'quantity': 0}]},
    )
    check('a run with nothing good, finished: the job is cancelled', code == 200 and body['result']['cancelled'] and body['job']['summary']['state'] == 'cancelled', body)
    check('material set to zero is not taken', stock_of(sheet['pk']) == before)

    job = new_job()
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/book/", json={'good': 12, 'runs': 1, 'finish': True})
    check('a short run, finished: the job is closed', code == 200 and body['result']['closed'] and body['job']['summary']['state'] == 'done', body)

    job = new_job()
    pads_before = stock_of(pad['pk'])
    it.post(f"{plugin}/job/{job['build']}/book/", {'good': 15, 'runs': 1}, expect=200)
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/book/", json={'good': 20, 'runs': 1})
    check('a second run which overshoots is booked in full', code == 200 and stock_of(pad['pk']) == pads_before + 35 and body['result']['closed'], stock_of(pad['pk']))
    wait_for(lambda: build_of(job['build'])['status_text'] == 'Complete')
    check('the build order is complete with 35 of 20', float(build_of(job['build'])['completed']) == 35)

    print('\nA part without a bill of materials')

    code, body = it.upload(f"{plugin}/part/{plain['pk']}/files/", 'gasket_x6.xcs', make_xcs(3, 2), expect=201)
    it.put(
        f"{plugin}/part/{plain['pk']}/",
        {'machine': laser['id'], 'files': [body['file']['attachment']], 'parts_per_run': 6, 'restock_to': 30, 'destination': other_shelf['pk']},
        expect=200,
    )
    job = new_job(part=plain)
    check('the parts go to the location of the link', job['destination'] == other_shelf['pk'] and not job['material'], job)
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/book/", json={'good': 6, 'runs': 1})
    check('booking works without material', code == 200 and stock_of(plain['pk']) == 6 and body['result']['closed'], body)

    print('\nWhat to make')

    overview = it.get(f'{plugin}/overview/', expect=200)
    by_part = {row['part']['pk']: row for row in overview['parts']}
    check('the linked parts are on the overview', {pad['pk'], plain['pk'], plate['pk']} <= set(by_part))
    check('each with its machine', by_part[pad['pk']]['link']['machine_name'] == f'Laser {tag}' and by_part[plate['pk']]['link']['machine_name'] == f'Carvera {tag}')
    counts = {m['id']: m['parts'] for m in overview['machines']}
    check('the machines say how many parts they make', counts[laser['id']] == 2 and counts[mill['id']] == 1, counts)
    check('the pad is above its minimum: nothing suggested', by_part[pad['pk']]['suggestion']['runs'] == 0, by_part[pad['pk']]['suggestion'])

    order = it.post('/api/build/', {'part': housing['pk'], 'quantity': 60, 'reference': f'BO-9{tag}'}, expect=201)
    it.post(f"/api/build/{order['pk']}/issue/", {}, expect=201)
    pads = stock_of(pad['pk'])
    data = it.get(f"{plugin}/part/{pad['pk']}/", expect=200)
    check('a build order in production which needs 120 pads counts as demand', data['numbers']['demand'] == 120, data['numbers'])
    shortfall = 40 - (pads - 120)
    check(
        'runs are suggested for the shortfall, because of the build order',
        data['suggestion']['runs'] == -(-shortfall // 20) and data['suggestion']['reason'] == 'build_demand',
        data['suggestion'],
    )
    it.post(f"/api/build/{order['pk']}/cancel/", {}, expect=201)

    print('\nWhen a file changes')

    code, body = it.upload(f"{plugin}/part/{pad['pk']}/files/", 'pad_x24.xcs', make_xcs(6, 4), expect=201)
    newer = body['file']
    body = it.put(put, link_body(files=[{'attachment': newer['attachment']}], parts_per_run=24, restock_to=100), expect=200)
    check('the part is linked to a new file', body['link']['files'][0]['filename'].startswith('pad_x24') and body['link']['parts_per_run'] == 24 and not body.get('made_assembly'))
    check('older jobs still have their own file', it.raw(f"{plugin}/job/{job['build']}/download/").status_code == 200)

    it.call('DELETE', f"/api/attachment/{newer['attachment']}/", expect=204)
    data = it.get(put, expect=200)
    check('a deleted attachment is noticed', data['link']['file_missing'], data['link'])
    code, body = it.call('POST', f"{plugin}/part/{pad['pk']}/make/", json={'runs': 1})
    check('and a job is refused until the part is linked again', code == 400 and 'no longer attached' in body['detail'], body)
    check('there is nothing to download', it.raw(f"{plugin}/part/{pad['pk']}/download/").status_code == 404)
    it.put(put, link_body(), expect=200)

    print('\nPermissions')

    anonymous = Api(args.inventree, {})
    code, _ = anonymous.call('GET', f'{plugin}/overview/')
    check('without a login nothing is shown', code in (401, 403), code)

    def new_user(name):
        user = it.post(
            '/api/user/',
            {'username': name, 'email': f'{name}@example.com', 'first_name': 'Check', 'last_name': name},
            expect=201,
        )
        it.put(f"/api/user/{user['pk']}/set-password/", {'password': 'check-Pass-12345', 'override_warning': True}, expect=200)
        token = requests.get(
            f'{args.inventree}/api/user/token/?name=check', auth=(name, 'check-Pass-12345'), timeout=30
        ).json()['token']

        return user, Api(args.inventree, {'Authorization': f'Token {token}'})

    _, norole = new_user(f'norole{tag}')
    code, _ = norole.call('GET', f'{plugin}/overview/')
    check('a user without roles is refused', code == 403, code)
    check('and cannot download a file', norole.raw(f"{plugin}/part/{pad['pk']}/download/").status_code == 403)
    check('nor see the machines', norole.call('GET', f'{plugin}/machines/')[0] == 403)

    viewer, viewing = new_user(f'viewer{tag}')
    group = it.post('/api/user/group/', {'name': f'viewers{tag}'}, expect=201)

    for role in group['roles']:
        if role['name'] in ('part', 'build'):
            it.patch(f"/api/user/ruleset/{role['pk']}/", {'can_view': True}, expect=200)

    it.patch(f"/api/user/{viewer['pk']}/", {'group_ids': [group['pk']]}, expect=200)

    code, body = viewing.call('GET', put)
    check(
        'a view-only user can see a part',
        code == 200 and not body['permissions']['make'] and not body['permissions']['link'] and not body['permissions']['manage'],
        code,
    )
    check('and download its files', viewing.raw(f"{plugin}/part/{pad['pk']}/download/").status_code == 200)
    code, _ = viewing.call('PUT', put, json=link_body())
    check('but not change the link', code == 403, code)
    code, _ = viewing.upload(f"{plugin}/part/{pad['pk']}/files/", 'x.xcs', project)
    check('nor attach a file', code == 403, code)
    code, _ = viewing.call('POST', f'{plugin}/machines/', json={'name': 'Mine', 'kind': 'cnc'})
    check('nor add a machine', code == 403, code)
    code, _ = viewing.call('PUT', f"{plugin}/machines/{laser['id']}/", json={'name': 'Mine', 'kind': 'cnc'})
    check('nor change one', code == 403, code)
    code, _ = viewing.call('DELETE', f"{plugin}/machines/{laser['id']}/")
    check('nor remove one', code == 403, code)
    code, _ = viewing.call('POST', f"{plugin}/part/{pad['pk']}/make/", json={'runs': 1})
    check('nor raise a job', code == 403, code)

    job = new_job()
    code, _ = viewing.call('POST', f"{plugin}/job/{job['build']}/book/", json={'good': 1, 'runs': 1})
    check('nor book parts', code == 403, code)
    code, _ = viewing.call('POST', f"{plugin}/job/{job['build']}/cancel/")
    check('nor cancel a job', code == 403, code)

    print('\nOdds and ends')

    code, _ = it.call('POST', f"{plugin}/job/{job['build']}/explode/")
    check('an unknown action is not found', code == 404, code)
    code, _ = it.call('GET', f"{plugin}/job/{order['pk']}/")
    check('an ordinary build order is not a workshop job', code == 404, code)
    code, _ = it.call('GET', f'{plugin}/part/99999999/')
    check('an unknown part is not found', code == 404, code)

    it.post(f"/api/build/{job['build']}/cancel/", {}, expect=201)
    # InvenTree cancels in the background when a worker is running
    wait_for(lambda: build_of(job['build'])['status_text'] == 'Cancelled')
    data = it.get(put, expect=200)
    check('a job cancelled from the build order page is no longer open', all(j['build'] != job['build'] for j in data['jobs']), data['jobs'])
    check('and shows as cancelled', next(j for j in data['history'] if j['build'] == job['build'])['summary']['state'] == 'cancelled')

    job = new_job()
    output = it.post(f"/api/build/{job['build']}/create-output/", {'quantity': 20}, expect=201)
    output = output[0] if isinstance(output, list) else output
    it.post(f"/api/build/{job['build']}/complete/", {'outputs': [{'output': output['pk']}], 'location': shelf['pk']})
    wait_for(lambda: float(build_of(job['build'])['completed']) == 20)
    data = it.get(f"{plugin}/job/{job['build']}/", expect=200)['job']
    check('parts completed on the build order page count for the job', data['completed'] == 20 and data['summary']['can_close'], data['summary'])
    code, body = it.call('POST', f"{plugin}/job/{job['build']}/close/")
    check('and the job can then be closed', code == 200 and body['job']['summary']['state'] == 'done', body)

    body = it.call('DELETE', put, expect=200)[1]
    check('the link is removed', body['link'] is None)
    check('the jobs of the part stay', len(body['history']) > 0)
    remaining = it.get(f"{plugin}/part/{pad['pk']}/files/", expect=200)['files']
    check('and so do its files', any(entry['attachment'] == file['attachment'] for entry in remaining))
    check('the part is off the overview', all(row['part']['pk'] != pad['pk'] for row in it.get(f'{plugin}/overview/')['parts']))

    it.call('DELETE', f"{plugin}/part/{plain['pk']}/", expect=200)
    code, body = it.call('DELETE', f"{plugin}/machines/{laser['id']}/")
    check('a machine can be removed once no part is linked to it', code == 200 and all(m['id'] != laser['id'] for m in body['machines']), body)
    data = it.get(f"{plugin}/job/{job['build']}/", expect=200)['job']
    check('its old jobs still say where they were made', data['machine']['name'] == f'Laser {tag}')

    print(f'\n{PASSED} passed, {len(FAILED)} failed')

    for name in FAILED:
        print(f'  FAILED: {name}')

    sys.exit(1 if FAILED else 0)


if __name__ == '__main__':
    main()
