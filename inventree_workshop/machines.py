"""The machines of the workshop.

A machine is whatever makes parts in-house from a file: a laser cutter, a CNC
mill, a vinyl cutter. Each linked part belongs to one machine. The list is
kept in the metadata of the plugin's own configuration record, under the key
'workshop':

    {"machines": [
        {"id": 1, "name": "xTool S1", "kind": "laser", "notes": "..."},
        {"id": 2, "name": "Makera Carvera", "kind": "cnc", "notes": ""}
    ]}

The kind only decides the icon and the wording of a few hints. Nothing is
sent to any machine.
"""

from __future__ import annotations

KEY = 'workshop'

KINDS = {
    'laser': 'Laser',
    'cnc': 'CNC',
    'other': 'Other',
}

NAME_LIMIT = 60
NOTES_LIMIT = 500
MACHINE_LIMIT = 50


class MachineError(Exception):
    """A machine could not be saved or removed. 'errors' maps a field to a message."""

    def __init__(self, errors: dict | str):
        if isinstance(errors, str):
            errors = {'detail': errors}

        super().__init__('; '.join(str(v) for v in errors.values()))
        self.errors = errors


def _config(plugin, required: bool = True):
    """The configuration record of the plugin, read from the database.

    InvenTree keeps one copy of the record for the length of a request. That
    copy would still show the old list after a change, so it is not used.
    """
    from plugin.models import PluginConfig

    config = PluginConfig.objects.filter(key=plugin.SLUG).first()

    if config is None and required:
        raise MachineError('The plugin has no configuration record yet. Activate it first.')

    return config


def _load(config) -> list:
    data = config.get_metadata(KEY) or {}
    machines = data.get('machines') if isinstance(data, dict) else None

    return [dict(entry) for entry in machines or [] if isinstance(entry, dict) and entry.get('id')]


def _store(config, machines: list) -> None:
    data = config.get_metadata(KEY) or {}
    data = dict(data) if isinstance(data, dict) else {}
    data['machines'] = machines
    config.set_metadata(KEY, data)


def list_machines(plugin) -> list:
    """Every machine, in the order they were added."""
    config = _config(plugin, required=False)

    return _load(config) if config is not None else []


def get_machine(plugin, pk) -> dict | None:
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return None

    return next((entry for entry in list_machines(plugin) if entry['id'] == pk), None)


def clean(data: dict, others: list) -> dict:
    """Validate a submitted machine against the other machines. Plain Python."""
    errors: dict = {}

    name = ' '.join(str(data.get('name') or '').split())

    if not name:
        errors['name'] = 'Give the machine a name'
    elif len(name) > NAME_LIMIT:
        errors['name'] = f'Keep the name below {NAME_LIMIT} characters'
    elif any(entry.get('name', '').casefold() == name.casefold() for entry in others):
        errors['name'] = 'There is a machine with this name already'

    kind = str(data.get('kind') or 'other').strip().lower()

    if kind not in KINDS:
        errors['kind'] = 'Choose laser, CNC or other'

    notes = str(data.get('notes') or '').strip()

    if len(notes) > NOTES_LIMIT:
        errors['notes'] = f'Keep the notes below {NOTES_LIMIT} characters'

    if errors:
        raise MachineError(errors)

    return {'name': name, 'kind': kind, 'notes': notes}


def save_machine(plugin, data: dict, pk=None) -> dict:
    """Add a machine, or change the one with the given id."""
    from django.db import transaction
    from plugin.models import PluginConfig

    with transaction.atomic():
        config = PluginConfig.objects.select_for_update().get(pk=_config(plugin).pk)
        machines = _load(config)

        if pk is None:
            if len(machines) >= MACHINE_LIMIT:
                raise MachineError(f'No more than {MACHINE_LIMIT} machines can be kept')

            machine = {'id': max((entry['id'] for entry in machines), default=0) + 1}
            machine.update(clean(data, machines))
            machines.append(machine)
        else:
            machine = next((entry for entry in machines if entry['id'] == int(pk)), None)

            if machine is None:
                raise MachineError('This machine does not exist')

            machine.update(clean(data, [entry for entry in machines if entry is not machine]))

        _store(config, machines)

    return machine


def delete_machine(plugin, pk, in_use: int = 0) -> None:
    """Remove a machine. 'in_use' is the number of parts which are linked to it."""
    from django.db import transaction
    from plugin.models import PluginConfig

    if in_use:
        raise MachineError(
            f"{in_use} {'part is' if in_use == 1 else 'parts are'} linked to this machine. Move them to another machine or remove their links first."
        )

    with transaction.atomic():
        config = PluginConfig.objects.select_for_update().get(pk=_config(plugin).pk)
        machines = _load(config)
        kept = [entry for entry in machines if entry['id'] != int(pk)]

        if len(kept) == len(machines):
            raise MachineError('This machine does not exist')

        _store(config, kept)
