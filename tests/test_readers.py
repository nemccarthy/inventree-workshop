import json

from inventree_workshop import links, machines, readers
from make_gcode import build as make_gcode
from make_xcs import build as make_xcs

import pytest


class TestDescribe:
    def test_xtool_project(self):
        summary = readers.describe(make_xcs(5, 4), 'pads.xcs')

        assert summary['recognised'] and summary['kind'] == 'xcs'
        assert summary['kind_name'] == 'xTool project'
        assert summary['facts'] == ['xTool S1', '112 × 67 mm', '1.1 mm thick']
        assert summary['operations'][0] == {'label': 'Cut × 20', 'detail': '35% · 60 mm/s', 'tone': 'cut'}
        assert summary['operations'][1]['tone'] == 'other'
        assert summary['parts_hint'] == 20
        assert summary['parts_hint_text'] == '20 shapes are set to cut in the file'
        assert summary['has_cover']

    def test_one_shape(self):
        assert readers.describe(make_xcs(1, 1), 'pad.xcs')['parts_hint_text'] == '1 shape is set to cut in the file'

    def test_several_passes_and_canvases(self):
        data = json.loads(make_xcs(2, 2))
        entry = data['device']['data']['value'][0][1]['displays']['value'][0][1]
        entry['data']['VECTOR_CUTTING']['parameter']['customize']['repeat'] = 3
        data['canvas'].append({'id': 'second', 'displays': []})

        summary = readers.describe(json.dumps(data).encode(), 'pads.xcs')

        assert any(operation['detail'].endswith('3 passes') for operation in summary['operations'])
        assert any('2 canvases' in note for note in summary['notes'])

    def test_gcode_program(self):
        summary = readers.describe(make_gcode(60, 40, 6), 'plate.nc')

        assert summary['recognised'] and summary['kind'] == 'gcode'
        assert summary['facts'][0] == '60 × 40 mm, 6 mm deep'
        assert 'up to 12,000 rpm' in summary['facts']
        assert [operation['label'] for operation in summary['operations']] == ['Tool 1', 'Tool 3']
        assert summary['parts_hint'] is None and not summary['has_cover']

    def test_gcode_from_makera_cam(self):
        summary = readers.describe(make_gcode(60, 40, 6, header=True, minutes=24), 'plate.nc')

        assert summary['facts'][:3] == ['for Makera Carvera', '60 × 40 mm, 6 mm deep', 'Aluminium plate 6 mm']
        assert 'about 24 min' in summary['facts']
        assert summary['minutes_hint'] == 24
        assert summary['operations'][0] == {'label': 'Tool 1', 'detail': '3.175 mm flat end mill', 'tone': 'other'}

    def test_tool_names_survive_being_stored_as_json(self):
        from inventree_workshop import gcode

        stored = json.loads(json.dumps(gcode.summarise(make_gcode(header=True), 'plate.nc')))
        result = readers._empty('gcode', 1)
        readers._describe_gcode(result, stored)

        assert result['operations'][1]['detail'] == '2 mm drill'

    def test_rotary_program_travels_along_one_axis(self):
        text = 'G90 G21\nM3 S9000\nG1 X0 Z5 A0 F500\nG1 X40 A360\nG1 X40 Z-2 A0\nM5\n'
        summary = readers.describe(text.encode(), 'figure.nc')

        assert summary['facts'][0] == '40 mm of travel, 2 mm deep'
        assert 'uses the rotary axis' in summary['facts']

    def test_other_files_are_described_as_nothing(self):
        summary = readers.describe(b'%PDF-1.7 ...', 'fixture.pdf')

        assert summary == {
            'recognised': False, 'kind': '', 'kind_name': '', 'size': 12, 'facts': [],
            'operations': [], 'notes': [], 'parts_hint': None, 'parts_hint_text': '',
            'minutes_hint': None, 'has_cover': False,
        }

    def test_known_kind_which_cannot_be_read(self):
        summary = readers.describe(b'{"canvas": 3, ', 'broken.xcs')

        assert summary['kind'] == 'xcs' and not summary['recognised'] and summary['facts'] == []

    def test_file_too_big_to_read(self):
        summary = readers.describe(None, 'huge.nc', size=900_000_000)

        assert not summary['recognised'] and summary['size'] == 900_000_000
        assert 'too big' in summary['notes'][0]

    def test_kind_goes_by_the_name(self):
        assert readers.kind_of('A.XCS') == 'xcs'
        assert readers.kind_of('side-a.nc') == 'gcode'
        assert readers.kind_of('plate.mkc') == ''
        assert readers.kind_of(None) == ''

    def test_cover_only_for_projects(self):
        assert readers.cover(make_xcs(2, 2), 'pads.xcs')[1] == 'image/png'
        assert readers.cover(make_xcs(2, 2), 'pads.nc') is None
        assert readers.cover(make_gcode(), 'plate.nc') is None
        assert readers.cover(None, 'pads.xcs') is None


class TestRequestedFiles:
    def test_in_order_with_labels(self):
        files = links.requested_files([{'attachment': 31, 'label': ' Side  A '}, {'attachment': '7'}, 12])

        assert files == [(31, 'Side A'), (7, ''), (12, '')]

    def test_needs_a_file(self):
        for value in ([], None, 'x', {}):
            with pytest.raises(links.LinkError) as error:
                links.requested_files(value)

            assert 'files' in error.value.errors

    def test_no_duplicates(self):
        with pytest.raises(links.LinkError):
            links.requested_files([{'attachment': 3}, {'attachment': 3}])

    def test_not_numbers(self):
        with pytest.raises(links.LinkError):
            links.requested_files([{'attachment': 'first'}])

    def test_limit(self):
        with pytest.raises(links.LinkError):
            links.requested_files(list(range(1, links.FILE_LIMIT + 2)))

    def test_label_is_cut_to_length(self):
        assert len(links.requested_files([{'attachment': 1, 'label': 'x' * 500}])[0][1]) == links.LABEL_LIMIT


class TestMachine:
    def test_clean(self):
        assert machines.clean({'name': '  Makera   Carvera ', 'kind': 'CNC', 'notes': ' in the back room '}, []) == {
            'name': 'Makera Carvera', 'kind': 'cnc', 'notes': 'in the back room',
        }

    def test_kind_defaults_to_other(self):
        assert machines.clean({'name': 'Vinyl cutter'}, [])['kind'] == 'other'

    def test_needs_a_name(self):
        with pytest.raises(machines.MachineError) as error:
            machines.clean({'name': '   '}, [])

        assert 'name' in error.value.errors

    def test_names_are_unique_whatever_the_case(self):
        with pytest.raises(machines.MachineError):
            machines.clean({'name': 'xtool s1'}, [{'id': 1, 'name': 'xTool S1'}])

    def test_unknown_kind(self):
        with pytest.raises(machines.MachineError) as error:
            machines.clean({'name': 'Lathe', 'kind': 'lathe'}, [])

        assert 'kind' in error.value.errors

    def test_long_values(self):
        with pytest.raises(machines.MachineError) as error:
            machines.clean({'name': 'x' * 100, 'notes': 'y' * 1000}, [])

        assert {'name', 'notes'} <= set(error.value.errors)
