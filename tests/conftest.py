"""The rules and the file readers are plain Python: they are tested without InvenTree."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dev'))

# These modules import InvenTree and Django only inside the functions which need them
from inventree_workshop import gcode, logic, machines, readers, xcs  # noqa: E402, F401
