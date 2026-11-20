"""The link between an InvenTree part and the files which make it on a machine.

The files (an xTool project, G-code programs, a CAM project, a fixture
drawing) are ordinary attachments of the part. The link is stored in the
metadata of the part, under the key 'workshop':

    {
        "machine": 2,                # see machines.py
        "files": [                   # in the order they are used
            {"attachment": 31, "filename": "plate_side-a.nc", "label": "Side A",
             "file_hash": "9f2c...", "file_size": 48213, "summary": {...}}
        ],
        "parts_per_run": 4,          # good parts from one run of the files
        "run_minutes": 25,           # machine time of one run (optional)
        "restock_to": 40,            # level to make up to (optional)
        "destination": 7,            # stock location for the parts (optional)
        "setup_notes": "Stock against the left stops, tool 1 is the 3 mm end mill"
    }

The hash (SHA-256) is there to notice when a file is replaced.
"""

from __future__ import annotations

import hashlib

from . import readers, xcs

KEY = 'workshop'

MODEL_TYPE = 'part'

# Comment on attachments which the plugin uploads
ATTACHMENT_COMMENT = 'Workshop job file'

NOTES_LIMIT = 2000
LABEL_LIMIT = 60
FILE_LIMIT = 12


class LinkError(Exception):
    """The link could not be saved. 'errors' maps a field name to a message."""

    def __init__(self, errors: dict | str):
        if isinstance(errors, str):
            errors = {'detail': errors}

        super().__init__('; '.join(str(v) for v in errors.values()))
        self.errors = errors


def get_link(part) -> dict | None:
    """The stored link of a part, or None."""
    metadata = part.metadata if isinstance(part.metadata, dict) else {}
    link = metadata.get(KEY)

    if isinstance(link, dict) and link.get('machine') and link.get('files'):
        return link

    return None


def linked_parts():
    """Queryset of the parts which are linked to a machine."""
    from part.models import Part

    return Part.objects.filter(metadata__has_key=KEY).order_by('name', 'pk')


def parts_on_machine(machine_id: int) -> int:
    """Number of parts which are linked to a machine."""
    return sum(
        1 for part in linked_parts() if (get_link(part) or {}).get('machine') == machine_id
    )


# The files


def attachments_of(part):
    """The file attachments of a part, newest first."""
    from common.models import Attachment

    return (
        Attachment.objects.filter(model_type=MODEL_TYPE, model_id=part.pk)
        .exclude(attachment='')
        .exclude(attachment__isnull=True)
        .order_by('-pk')
    )


def get_attachment(part, pk):
    """The file attachment of the part with the given id, or None."""
    try:
        return attachments_of(part).filter(pk=int(pk)).first()
    except (TypeError, ValueError):
        return None


def file_name(attachment) -> str:
    import os

    return os.path.basename(attachment.attachment.name or '')


def read_file(attachment) -> tuple[str, int, bytes | None]:
    """Hash, size and content of an attached file.

    The content is None when the file is too big to be read for its details.
    Raises OSError if the file is missing from storage.
    """
    digest = hashlib.sha256()
    chunks: list[bytes] | None = []
    size = 0

    with attachment.attachment.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)
            size += len(chunk)

            if chunks is not None:
                if size > xcs.READ_LIMIT:
                    chunks = None
                else:
                    chunks.append(chunk)

    return digest.hexdigest(), size, b''.join(chunks) if chunks is not None else None


def describe_file(attachment) -> dict:
    """An attached file with what it says about itself."""
    name = file_name(attachment)

    try:
        file_hash, size, content = read_file(attachment)
    except (OSError, ValueError):
        return {
            'attachment': attachment.pk,
            'filename': name,
            'missing': True,
            'summary': readers.describe(b'', name, size=0),
        }

    return {
        'attachment': attachment.pk,
        'filename': name,
        'file_hash': file_hash,
        'file_size': size,
        'missing': False,
        'summary': readers.describe(content, name, size=size),
    }


def store_file(part, upload, user=None):
    """Attach an uploaded file to the part. Returns the attachment."""
    from common.models import Attachment
    from django.core.exceptions import ValidationError

    attachment = Attachment(
        model_type=MODEL_TYPE,
        model_id=part.pk,
        attachment=upload,
        comment=ATTACHMENT_COMMENT,
        upload_user=user,
    )

    try:
        attachment.full_clean()
        attachment.save()
    except ValidationError as exc:
        raise LinkError({'files': '; '.join(exc.messages)}) from None

    return attachment


# The link


def _positive_int(value, field: str, errors: dict, optional: bool = True):
    if value in (None, ''):
        if not optional:
            errors[field] = 'This value is required'

        return None

    try:
        number = int(value)

        if number != float(value):
            raise ValueError
    except (TypeError, ValueError):
        errors[field] = 'Enter a whole number'
        return None

    if number < 1:
        errors[field] = 'Enter a whole number greater than zero'
        return None

    return number


def _positive_number(value, field: str, errors: dict, zero: bool = False):
    if value in (None, ''):
        return None

    try:
        number = float(value)

        if number != number or number in (float('inf'), float('-inf')):
            raise ValueError

        if number < 0 or (number == 0 and not zero):
            raise ValueError
    except (TypeError, ValueError):
        errors[field] = 'Enter a number, or leave it empty'
        return None

    return number


def requested_files(data) -> list:
    """The files of a submitted link: [(attachment id, label), ...]. Plain Python.

    Raises LinkError if the list is not usable.
    """
    entries = data if isinstance(data, list) else []
    result = []
    seen = set()

    for entry in entries:
        if isinstance(entry, dict):
            pk, label = entry.get('attachment'), entry.get('label')
        else:
            pk, label = entry, ''

        try:
            pk = int(pk)
        except (TypeError, ValueError):
            raise LinkError({'files': 'The list of files is not in the form the plugin expects'}) from None

        if pk in seen:
            raise LinkError({'files': 'The same file is in the list twice'})

        seen.add(pk)
        result.append((pk, ' '.join(str(label or '').split())[:LABEL_LIMIT]))

    if not result:
        raise LinkError({'files': 'Choose at least one file'})

    if len(result) > FILE_LIMIT:
        raise LinkError({'files': f'No more than {FILE_LIMIT} files can be linked to a part'})

    return result


def build_link(part, data: dict, machine: dict | None, user=None) -> dict:
    """Validate the submitted link against the part and its attachments.

    'machine' is the machine named in the data, or None if there is no such
    machine. Returns the link to store. Raises LinkError with a message for
    each field which is wrong.
    """
    import InvenTree.helpers
    from stock.models import StockLocation

    errors: dict = {}

    if part.trackable:
        raise LinkError(
            'This part is tracked by serial number. Parts made in the workshop are booked into stock as one batch, so serialised parts cannot be linked.'
        )

    if part.virtual:
        raise LinkError('A virtual part cannot be made.')

    if not part.active:
        raise LinkError('This part is inactive.')

    if machine is None:
        errors['machine'] = 'Choose the machine which makes this part'

    per_run = _positive_int(data.get('parts_per_run'), 'parts_per_run', errors, optional=False)
    destination = _positive_int(data.get('destination'), 'destination', errors)
    restock_to = _positive_number(data.get('restock_to'), 'restock_to', errors, zero=True)
    run_minutes = _positive_number(data.get('run_minutes'), 'run_minutes', errors)

    notes = str(data.get('setup_notes') or '').strip()

    if len(notes) > NOTES_LIMIT:
        errors['setup_notes'] = f'Keep the notes below {NOTES_LIMIT} characters'

    if destination and not StockLocation.objects.filter(pk=destination).exists():
        errors['destination'] = 'This stock location does not exist'

    files = []

    try:
        wanted = requested_files(data.get('files'))
    except LinkError as exc:
        errors.update(exc.errors)
        wanted = []

    for pk, label in wanted:
        attachment = get_attachment(part, pk)

        if attachment is None:
            errors['files'] = 'One of the files is not attached to the part'
            break

        file = describe_file(attachment)

        if file['missing']:
            errors['files'] = f"'{file['filename']}' is missing from the InvenTree file storage"
            break

        files.append({
            'attachment': file['attachment'],
            'filename': file['filename'],
            'label': label,
            'file_hash': file['file_hash'],
            'file_size': file['file_size'],
            'summary': file['summary'],
        })

    if errors:
        raise LinkError(errors)

    previous = get_link(part) or {}

    return {
        'machine': machine['id'],
        'files': files,
        'parts_per_run': per_run,
        'run_minutes': run_minutes,
        'restock_to': restock_to,
        'destination': destination,
        'setup_notes': notes,
        'linked': previous.get('linked') or InvenTree.helpers.current_date().isoformat(),
        'linked_by': previous.get('linked_by') or (user.username if user else None),
    }


def save_link(part, link: dict) -> bool:
    """Store the link on the part.

    InvenTree only raises build orders for assemblies, so the part is marked
    as an assembly if it is not one yet. Returns True if that was changed.
    """
    made_assembly = False

    if not part.assembly:
        part.assembly = True
        made_assembly = True

    metadata = dict(part.metadata) if isinstance(part.metadata, dict) else {}
    metadata[KEY] = link
    part.metadata = metadata
    part.save()

    return made_assembly


def clear_link(part) -> None:
    """Remove the link from the part. The files and the jobs stay."""
    metadata = dict(part.metadata) if isinstance(part.metadata, dict) else {}

    if KEY in metadata:
        del metadata[KEY]
        part.metadata = metadata
        part.save()


def check_files(part, link: dict, verify: bool = True) -> list:
    """The state of the linked files, as they are in storage now.

    One entry for each file of the link, in order:

    'missing': the attachment was deleted, or its file is gone
    'changed': the file is not the one which was linked (same attachment,
               different content)

    Without 'verify' only the attachments are looked up: the files are not
    read, so one which was changed or lost in storage goes unnoticed.
    """
    result = []

    for entry in link.get('files') or []:
        attachment = get_attachment(part, entry.get('attachment'))
        state = {
            'attachment': entry.get('attachment'),
            'object': attachment,
            'missing': attachment is None,
            'changed': False,
            'file_hash': entry.get('file_hash'),
        }

        if attachment is not None and verify:
            try:
                file_hash, _size, _content = read_file(attachment)
                state['changed'] = bool(entry.get('file_hash')) and entry['file_hash'] != file_hash
                state['file_hash'] = file_hash
            except (OSError, ValueError):
                state['missing'] = True

        result.append(state)

    return result
