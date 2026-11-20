import io
import json
import zipfile

from inventree_workshop import xcs
from make_xcs import build


def document(**changes) -> dict:
    data = json.loads(build(5, 4))
    data.update(changes)

    return data


def encode(data: dict) -> bytes:
    return json.dumps(data).encode('utf-8')


class TestSummarise:
    def test_grid_of_pads(self):
        summary = xcs.summarise(build(5, 4), 'pads.xcs')

        assert summary['recognised'] and summary['project']
        assert summary['machine'] == 'S1'
        assert summary['app_version'] == '2.2.23'
        assert summary['canvases'] == 1
        assert summary['shapes'] == 21
        assert summary['cut_shapes'] == 20
        assert (summary['width'], summary['height']) == (112.0, 67.0)
        assert summary['thickness'] == 1.1
        assert summary['has_cover']

    def test_operations_are_grouped_with_their_settings(self):
        operations = xcs.summarise(build(5, 4))['operations']

        assert [(entry['label'], entry['count']) for entry in operations] == [('Cut', 20), ('Score', 1)]
        assert (operations[0]['power'], operations[0]['speed'], operations[0]['passes']) == (35, 60, 1)

    def test_different_settings_make_different_groups(self):
        data = document()
        entries = data['device']['data']['value'][0][1]['displays']['value']
        entries[0][1]['data']['VECTOR_CUTTING']['parameter']['customize']['power'] = 80

        operations = xcs.summarise(encode(data))['operations']
        cuts = [entry for entry in operations if entry['type'] == 'VECTOR_CUTTING']

        assert sorted((entry['power'], entry['count']) for entry in cuts) == [(35, 19), (80, 1)]

    def test_the_set_of_values_in_use_is_read(self):
        data = document()
        entry = data['device']['data']['value'][0][1]['displays']['value'][0][1]
        entry['data']['VECTOR_CUTTING'] = {
            'materialType': 'official',
            'parameter': {
                'customize': {'power': 1, 'speed': 1, 'repeat': 1},
                'official': {'power': 90, 'speed': 12, 'repeat': 2},
            },
        }

        operations = xcs.summarise(encode(data))['operations']

        assert any(
            (item['power'], item['speed'], item['passes']) == (90, 12, 2) for item in operations
        )

    def test_hidden_and_ignored_shapes_are_left_out(self):
        data = document()
        shapes = data['canvas'][0]['displays']
        shapes[0]['visible'] = False
        data['device']['data']['value'][0][1]['displays']['value'][1][1]['processIgnore'] = True

        summary = xcs.summarise(encode(data))

        assert summary['shapes'] == 19 and summary['skipped'] == 2 and summary['cut_shapes'] == 18

    def test_the_open_canvas_is_the_one_described(self):
        data = document()
        other = {'id': 'other', 'title': 'spare', 'displays': []}
        data['canvas'].insert(0, other)

        summary = xcs.summarise(encode(data))

        assert summary['canvases'] == 2 and summary['cut_shapes'] == 20

    def test_material_name(self):
        data = document()
        data['device']['materialList'] = [{'id': 7, 'name': {'de': 'Klebefolie', 'en': 'Adhesive film'}}]
        data['device']['data']['value'][0][1]['data']['LASER_PLANE']['material'] = 7

        assert xcs.summarise(encode(data))['material'] == 'Adhesive film'

    def test_modified_date(self):
        assert xcs.summarise(encode(document(modify=1733344934779)))['modified'] == '2024-12-04T20:42:14+00:00'

    def test_byte_order_mark(self):
        assert xcs.summarise(b'\xef\xbb\xbf' + build(2, 2))['recognised']

    def test_inside_a_zip(self):
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('readme.txt', 'hello')
            archive.writestr('project.json', build(2, 2))

        summary = xcs.summarise(buffer.getvalue(), 'pads.xs')

        assert summary['recognised'] and summary['cut_shapes'] == 4


class TestNotAProject:
    def check(self, content: bytes, name: str = 'file.xcs'):
        summary = xcs.summarise(content, name)

        assert summary['recognised'] is False
        assert xcs.cover(content) is None

        return summary

    def test_empty(self):
        assert self.check(b'')['size'] == 0

    def test_text(self):
        assert self.check(b'not a project', 'notes.txt')['project'] is False

    def test_cut_off(self):
        self.check(build(2, 2)[:300])

    def test_other_json(self):
        self.check(b'{"hello": 1}')
        self.check(b'[1, 2, 3]')
        self.check(b'{"canvas": 3}')

    def test_binary(self):
        self.check(bytes(range(256)) * 10)

    def test_broken_zip(self):
        self.check(b'PK\x03\x04' + b'\x00' * 40)

    def test_deep_nesting(self):
        self.check(b'[' * 100000)

    def test_odd_values_do_not_break_it(self):
        data = document()
        data['device'] = 'none'
        data['canvas'][0]['displays'] = [None, 3, {'x': 'a'}, {'id': 1, 'x': float('1e400')}]

        summary = xcs.summarise(encode(data).replace(b'Infinity', b'1e999'))

        assert summary['recognised'] and summary['cut_shapes'] == 0 and summary['width'] is None

    def test_name_decides_what_counts_as_a_project_file(self):
        assert xcs.is_project_name('Pads.XCS') and xcs.is_project_name('pads.xs')
        assert not xcs.is_project_name('pads.svg') and not xcs.is_project_name(None)


class TestCover:
    def test_picture(self):
        picture, content_type = xcs.cover(build(2, 2))

        assert content_type == 'image/png' and picture.startswith(b'\x89PNG')

    def test_no_picture(self):
        data = document()
        del data['cover']

        assert xcs.cover(encode(data)) is None
        assert xcs.summarise(encode(data))['has_cover'] is False

    def test_only_pictures_are_passed_on(self):
        for value in (
            'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=',
            'data:text/html;base64,PGI+aGk8L2I+',
            'data:image/png,not-base64',
            'https://example.com/picture.png',
            'data:image/png;base64,',
        ):
            assert xcs.cover(encode(document(cover=value))) is None, value
