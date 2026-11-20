from inventree_workshop import gcode
from make_gcode import build


def read(text: str) -> dict:
    return gcode.summarise(text.encode('ascii'), 'part.nc')


class TestSummarise:
    def test_plate_with_holes(self):
        summary = gcode.summarise(build(60, 40, 6), 'plate.nc')

        assert summary['recognised']
        assert summary['tools'] == [1, 3]
        assert summary['tool_changes'] == 2
        assert summary['spindle_max'] == 12000
        assert summary['feed_max'] == 600
        assert (summary['width'], summary['height'], summary['depth']) == (60, 40, 6)
        assert summary['units'] == 'mm'
        assert not summary['rotary'] and not summary['partial']

    def test_rapids_do_not_count_as_travel(self):
        summary = read('G90 G21\nM3 S8000\nG0 X500 Y500\nG0 X10 Y10\nG1 X20 Y15 F300\nG1 X10 Y10\nM5\n')

        assert (summary['width'], summary['height']) == (10, 5)

    def test_motion_is_modal(self):
        summary = read('G90\nM3 S8000\nG1 X0 Y0 F100\nX30\nY20\nX0\nM5\n')

        assert (summary['width'], summary['height']) == (30, 20)

    def test_relative_moves(self):
        summary = read('G21 G91\nM3 S9000\nG1 X10 F200\nG1 Y5\nG1 X-10\nG1 Y-5\nG1 Z-2\nM5\n')

        assert (summary['width'], summary['height'], summary['depth']) == (10, 5, 2)

    def test_inches_are_converted(self):
        summary = read('G20 G90\nM3 S10000\nG1 X0 Y0 F10\nG1 X2 Y1\nG1 Z-0.25\nM5\n')

        assert summary['units'] == 'inch'
        assert (summary['width'], summary['height']) == (50.8, 25.4)
        assert summary['depth'] == 6.35
        assert summary['feed_max'] == 254

    def test_comments_are_ignored(self):
        summary = read('(T99 is not a tool) \nG90 ; G1 X999\nM6 T2 (the 2 mm end mill)\nM3 S5000\nG1 X5 Y5 F100\nG1 X10\nM5\n')

        assert summary['tools'] == [2]
        assert summary['width'] == 5

    def test_machine_moves_and_homing_are_left_out(self):
        summary = read('G90\nM3 S5000\nG1 X0 Y0 F100\nG1 X10 Y10\nG53 G1 X-300 Y-200\nG28 X0 Y0\nG1 X12\nM5\n')

        assert (summary['width'], summary['height']) == (12, 10)

    def test_no_depth_when_nothing_goes_below_zero(self):
        assert read('G90\nM3 S5000\nG1 X0 Y0 Z2 F100\nG1 X10\nG1 Y10\nM5\n')['depth'] is None

    def test_rotary_axis(self):
        assert read('G90\nM3 S5000\nG1 X0 Y0 F100\nG1 X10 A90\nG1 X20 A180\nM5\n')['rotary']

    def test_lower_case_and_spaces(self):
        summary = read('g90 g21\nm6 t4\nm3 s 6000\ng1 x 0 y 0 f 120\ng1 x 8 y 3\nm5\n')

        assert summary['tools'] == [4] and summary['width'] == 8 and summary['spindle_max'] == 6000

    def test_long_program_is_read_in_part(self):
        lines = ['G90', 'M6 T1', 'M3 S9000'] + ['G1 X1 Y1 F100', 'G1 X2 Y2'] * 150000

        summary = read('\n'.join(lines))

        assert summary['partial'] and summary['lines'] == gcode.LINE_LIMIT


class TestMakeraHeader:
    def test_header_is_read(self):
        summary = gcode.summarise(build(60, 40, 6, header=True, minutes=24), 'plate.nc')

        assert summary['made_for'] == 'Makera Carvera'
        assert summary['material'] == 'Aluminium plate 6 mm'
        assert summary['stock'] == [80, 60, 6]
        assert summary['seconds'] == 1440
        assert summary['tool_names'] == {1: '3.175 mm flat end mill', 3: '2 mm drill'}
        assert summary['toolpaths'] == ['[T1]2D Contour']
        # The program itself is read as before
        assert summary['tools'] == [1, 3] and summary['width'] == 60

    def test_no_header(self):
        summary = gcode.summarise(build(), 'plate.nc')

        assert summary['made_for'] is None and summary['seconds'] is None
        assert summary['tool_names'] == {} and summary['toolpaths'] == []

    def test_odd_header_lines_do_not_break_it(self):
        text = (
            ';@MKR|\n;@MKR\n;@MKR|TIME|seconds=soon\n;@MKR|TIME\n;@MKR|STOCK|length=10|width=-4|height=x\n'
            ';@MKR|TOOL|number=one|name=x\n;@MKR|TOOL|number=2\n;@MKR|MACHINE|name=' + 'm' * 500 + '\n'
            'G90\nM3 S5000\nG1 X0 Y0 F100\nG1 X10 Y10\nM5\n'
        )

        summary = read(text)

        assert summary['recognised'] and summary['width'] == 10
        assert summary['seconds'] is None and summary['stock'] is None and summary['tool_names'] == {}
        assert len(summary['made_for']) == 80


class TestDamagedLines:
    def test_a_coordinate_out_of_all_reach_is_left_out(self):
        summary = read('G90\nM3 S5000\nG1 X0 Y0 Z-1 F100\nG1 X10 Y10\nG1Z-58145e87f0c3f3ee8848c97fcdec1f620.300F300.0\nG1 X12\nM5\n')

        assert summary['depth'] == 1 and summary['width'] == 12


class TestNotAProgram:
    def test_empty(self):
        assert gcode.summarise(b'', 'a.nc')['recognised'] is False

    def test_text(self):
        assert read('These are my notes about the job.\nNothing to see.\n')['recognised'] is False

    def test_binary(self):
        assert gcode.summarise(bytes(range(256)) * 20, 'a.nc')['recognised'] is False

    def test_too_little_to_tell(self):
        assert read('G90\n')['recognised'] is False

    def test_odd_numbers_do_not_break_it(self):
        assert read('G1 X1e999 Y--5 F.\nG1 X.5 Y5.\nM3 S+100\nG1 X1\n')['recognised']

    def test_names(self):
        assert gcode.is_gcode_name('Plate.NC') and gcode.is_gcode_name('a.gcode') and gcode.is_gcode_name('a.cnc')
        assert not gcode.is_gcode_name('a.xcs') and not gcode.is_gcode_name(None)
