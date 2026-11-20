"""API views for the Workshop plugin.

All endpoints are served below /plugin/workshop/ and accept session or token
authentication, so they can also be used from scripts.
"""

from __future__ import annotations

import tempfile
import zipfile

from django.http import FileResponse, HttpResponse
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import jobs, links, logic, machines, planning, readers
from .core import SLUG


def _plugin():
    from plugin.registry import registry

    plugin = registry.get_plugin(SLUG)

    if plugin is None:
        raise NotFound('The Workshop plugin is not active')

    return plugin


def _can(user, role: str, permission: str) -> bool:
    from users.permissions import check_user_role

    return bool(user and check_user_role(user, role, permission))


def user_permissions(user) -> dict:
    """What the user may do."""
    return {
        'view': _can(user, 'part', 'view'),
        # The link and the files are stored against the part. The list of
        # machines goes with it: without a machine nothing can be linked
        'link': _can(user, 'part', 'change'),
        # A job is a build order
        'make': _can(user, 'build', 'add'),
        'manage': _can(user, 'build', 'change'),
    }


def _error(message, code=status.HTTP_400_BAD_REQUEST, **extra) -> Response:
    return Response({'detail': message, **extra}, status=code)


class WorkshopView(APIView):
    """Base class: every endpoint needs at least permission to view parts."""

    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        """Check the role permissions before handling the request."""
        super().initial(request, *args, **kwargs)

        if not _can(request.user, 'part', 'view'):
            raise PermissionDenied()

    def require(self, request, name: str):
        """Raise an error unless the user has the named permission."""
        if not user_permissions(request.user).get(name):
            raise PermissionDenied()

    def handle_exception(self, exc):
        """Answer with a readable message when a rule says no."""
        if isinstance(exc, jobs.JobError):
            return _error(str(exc))

        if isinstance(exc, (links.LinkError, machines.MachineError)):
            return _error(str(exc), errors=exc.errors)

        return super().handle_exception(exc)


def _part(pk: int):
    from part.models import Part

    part = Part.objects.filter(pk=pk).first()

    if part is None:
        raise NotFound('Part not found')

    return part


def _part_label(part) -> dict:
    return {
        'pk': part.pk,
        'name': part.name,
        'ipn': part.IPN or '',
        'description': part.description or '',
        'units': part.units or '',
        'active': part.active,
        'assembly': part.assembly,
        'trackable': part.trackable,
        'minimum_stock': float(part.minimum_stock or 0),
        'default_location': getattr(part.get_default_location(), 'pk', None),
    }


def _location_name(pk) -> str | None:
    from stock.models import StockLocation

    if not pk:
        return None

    location = StockLocation.objects.filter(pk=pk).first()

    return location.pathstring if location else None


def _machines_out(plugin) -> list:
    """The machines, each with the number of parts linked to it."""
    counts: dict = {}

    for part in links.linked_parts():
        link = links.get_link(part)

        if link:
            counts[link['machine']] = counts.get(link['machine'], 0) + 1

    return [
        {**machine, 'kind_name': machines.KINDS.get(machine.get('kind'), 'Other'), 'parts': counts.get(machine['id'], 0)}
        for machine in machines.list_machines(plugin)
    ]


def _link_out(plugin, part, link: dict | None, verify: bool = False, known=None) -> dict | None:
    """The link with its machine and the state of its files."""
    if not link:
        return None

    if known is None:
        known = {machine['id']: machine for machine in machines.list_machines(plugin)}

    machine = known.get(link.get('machine'))
    states = links.check_files(part, link, verify=verify)

    files = [
        {**entry, 'missing': state['missing'], 'changed': state['changed']}
        for entry, state in zip(link.get('files') or [], states)
    ]

    return {
        **link,
        'files': files,
        'machine_name': machine['name'] if machine else None,
        'machine_kind': machine.get('kind') if machine else None,
        'machine_notes': machine.get('notes') if machine else '',
        'machine_missing': machine is None,
        'destination_name': _location_name(link.get('destination')),
        'file_missing': any(state['missing'] for state in states),
        'file_changed': any(state['changed'] for state in states),
    }


def _materials(part) -> list:
    """What the bill of materials says one part uses, for display."""
    result = []

    for bom_item in part.get_bom_items(include_virtual=False):
        material = bom_item.sub_part

        result.append({
            'part': material.pk,
            'name': material.name,
            'ipn': material.IPN or '',
            'units': material.units or '',
            'per_part': float(bom_item.quantity),
            'consumable': bool(bom_item.consumable),
            # Taken from stock when parts are booked
            'taken': not (bom_item.consumable or material.trackable),
        })

    return result


def _part_out(plugin, part, verify: bool = False) -> dict:
    """Everything the part panel shows."""
    link = links.get_link(part)
    numbers = planning.part_numbers(part, plugin.include_pending())
    open_jobs = jobs.active_jobs(part)
    finished = jobs.recent_jobs(part, limit=8, finished_only=True)

    return {
        'part': _part_label(part),
        'link': _link_out(plugin, part, link, verify=verify),
        'materials': _materials(part) if link else [],
        'numbers': numbers,
        'suggestion': planning.suggestion(link, numbers) if link else None,
        'jobs': [jobs.describe(build) for build in reversed(open_jobs)],
        'history': [jobs.describe(build) for build in finished],
        'machines': machines.list_machines(plugin),
        'include_pending': plugin.include_pending(),
    }


def _attachment_out(attachment, linked: set) -> dict:
    name = links.file_name(attachment)
    kind = readers.kind_of(name)

    return {
        'attachment': attachment.pk,
        'filename': name,
        'file_size': attachment.file_size or 0,
        'comment': attachment.comment or '',
        'uploaded': attachment.upload_date.isoformat() if attachment.upload_date else None,
        'uploaded_by': attachment.upload_user.username if attachment.upload_user else None,
        'kind': kind,
        'kind_name': readers.KIND_NAMES.get(kind, ''),
        'linked': attachment.pk in linked,
    }


def _download(attachment) -> FileResponse:
    try:
        handle = attachment.attachment.open('rb')
    except (OSError, ValueError):
        raise NotFound('The file is missing from the InvenTree file storage') from None

    response = FileResponse(
        handle,
        as_attachment=True,
        filename=links.file_name(attachment),
        content_type='application/octet-stream',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'

    return response


def _safe_name(text: str) -> str:
    kept = ''.join(ch if ch.isalnum() or ch in '-_.' else '-' for ch in str(text or '').strip())

    return kept.strip('-.')[:80] or 'files'


def _download_set(part, entries: list, name: str):
    """The files of a link or a job as one download: the file itself, or a zip of them."""
    found = []

    for entry in entries:
        attachment = links.get_attachment(part, entry.get('attachment'))

        if attachment is not None:
            found.append(attachment)

    if not found:
        raise NotFound('The files are no longer attached to the part')

    if len(entries) == 1:
        return _download(found[0])

    # Kept in memory while small, on disk beyond that
    buffer = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    used: set = set()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, attachment in enumerate(found, start=1):
            filename = links.file_name(attachment) or f'file-{index}'

            if filename in used:
                filename = f'{index}-{filename}'

            used.add(filename)

            try:
                with attachment.attachment.open('rb') as source, archive.open(filename, 'w') as target:
                    while True:
                        chunk = source.read(1024 * 1024)

                        if not chunk:
                            break

                        target.write(chunk)
            except (OSError, ValueError):
                raise NotFound(
                    f"'{filename}' is missing from the InvenTree file storage"
                ) from None

    buffer.seek(0)

    response = FileResponse(
        buffer,
        as_attachment=True,
        filename=f'{_safe_name(name)}.zip',
        content_type='application/zip',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'

    return response


class MachinesView(WorkshopView):
    """GET / POST /plugin/workshop/machines/ - the machines of the workshop.

    POST body: {"name": "Makera Carvera", "kind": "cnc", "notes": ""}
    (kind: laser, cnc or other)
    """

    def get(self, request, *args, **kwargs):
        return Response({
            'machines': _machines_out(_plugin()),
            'kinds': machines.KINDS,
            'permissions': user_permissions(request.user),
        })

    def post(self, request, *args, **kwargs):
        self.require(request, 'link')

        plugin = _plugin()
        data = request.data if isinstance(request.data, dict) else {}
        machine = machines.save_machine(plugin, data)

        return Response(
            {'machine': machine, 'machines': _machines_out(plugin)},
            status=status.HTTP_201_CREATED,
        )


class MachineView(WorkshopView):
    """PUT / DELETE /plugin/workshop/machines/<id>/ - change or remove a machine."""

    def put(self, request, pk, *args, **kwargs):
        self.require(request, 'link')

        plugin = _plugin()

        if machines.get_machine(plugin, pk) is None:
            raise NotFound('Machine not found')

        data = request.data if isinstance(request.data, dict) else {}
        machine = machines.save_machine(plugin, data, pk=pk)

        return Response({'machine': machine, 'machines': _machines_out(plugin)})

    def delete(self, request, pk, *args, **kwargs):
        self.require(request, 'link')

        plugin = _plugin()

        if machines.get_machine(plugin, pk) is None:
            raise NotFound('Machine not found')

        machines.delete_machine(plugin, pk, in_use=links.parts_on_machine(int(pk)))

        return Response({'machines': _machines_out(plugin)})


class PartView(WorkshopView):
    """GET / PUT / DELETE /plugin/workshop/part/<id>/ - a part and its link.

    PUT body: {"machine": 2, "files": [{"attachment": 31, "label": "Side A"}],
               "parts_per_run": 4, "run_minutes": 25, "restock_to": 40,
               "destination": 7, "setup_notes": "..."}
    """

    def get(self, request, pk, *args, **kwargs):
        plugin = _plugin()

        return Response({
            # Reading the files here notices one which was replaced in storage
            **_part_out(plugin, _part(pk), verify=True),
            'permissions': user_permissions(request.user),
        })

    def put(self, request, pk, *args, **kwargs):
        """Link the part to a machine and its files, or change the link."""
        self.require(request, 'link')

        plugin = _plugin()
        part = _part(pk)
        data = request.data if isinstance(request.data, dict) else {}

        machine = machines.get_machine(plugin, data.get('machine'))
        link = links.build_link(part, data, machine, request.user)
        made_assembly = links.save_link(part, link)

        return Response({
            **_part_out(plugin, part),
            'permissions': user_permissions(request.user),
            'made_assembly': made_assembly,
        })

    def delete(self, request, pk, *args, **kwargs):
        """Remove the link. The files and the jobs stay as they are."""
        self.require(request, 'link')

        plugin = _plugin()
        part = _part(pk)
        links.clear_link(part)

        return Response({
            **_part_out(plugin, part),
            'permissions': user_permissions(request.user),
        })


class FilesView(WorkshopView):
    """The files attached to a part.

    GET  /plugin/workshop/part/<id>/files/                 the attachments
    GET  /plugin/workshop/part/<id>/files/?describe=31     one of them, read
    POST /plugin/workshop/part/<id>/files/                 attach a file (form field 'file')
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, pk, *args, **kwargs):
        part = _part(pk)
        link = links.get_link(part) or {}
        linked = {entry.get('attachment') for entry in link.get('files') or []}

        describe = request.query_params.get('describe')

        if describe:
            attachment = links.get_attachment(part, describe)

            if attachment is None:
                raise NotFound('This file is not attached to the part')

            return Response({'file': links.describe_file(attachment)})

        return Response({
            'files': [
                _attachment_out(attachment, linked)
                for attachment in links.attachments_of(part).select_related('upload_user')[:200]
            ]
        })

    def post(self, request, pk, *args, **kwargs):
        self.require(request, 'link')

        part = _part(pk)
        upload = request.FILES.get('file')

        if upload is None:
            return _error('No file was sent', errors={'files': 'Choose a file'})

        attachment = links.store_file(part, upload, request.user)

        return Response(
            {'file': links.describe_file(attachment)}, status=status.HTTP_201_CREATED
        )


class PartFileView(WorkshopView):
    """GET /plugin/workshop/part/<id>/file/<attachment>/ - one file of the part, as a download."""

    def get(self, request, pk, attachment, *args, **kwargs):
        found = links.get_attachment(_part(pk), attachment)

        if found is None:
            raise NotFound('This file is not attached to the part')

        return _download(found)


class PartDownloadView(WorkshopView):
    """GET /plugin/workshop/part/<id>/download/ - the linked files: the file, or a zip of them."""

    def get(self, request, pk, *args, **kwargs):
        part = _part(pk)
        link = links.get_link(part)

        if not link:
            raise NotFound('This part is not linked to a machine and its files')

        return _download_set(part, link['files'], f'{part.IPN or part.name}-files')


class PreviewView(WorkshopView):
    """GET /plugin/workshop/part/<id>/preview/?attachment=31 - the picture stored in a file."""

    def get(self, request, pk, *args, **kwargs):
        part = _part(pk)
        chosen = request.query_params.get('attachment')

        if not chosen:
            link = links.get_link(part)

            if not link:
                raise NotFound('No preview')

            chosen = link['files'][0]['attachment']

        attachment = links.get_attachment(part, chosen)

        if attachment is None:
            raise NotFound('This file is not attached to the part')

        try:
            _hash, _size, content = links.read_file(attachment)
        except (OSError, ValueError):
            raise NotFound('No preview') from None

        picture = readers.cover(content, links.file_name(attachment))

        if picture is None:
            raise NotFound('No preview')

        response = HttpResponse(picture[0], content_type=picture[1])
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, max-age=300'

        return response


class MakeView(WorkshopView):
    """POST /plugin/workshop/part/<id>/make/ - raise a job.

    Body: {"runs": 3} or {"quantity": 50} (rounded up to whole runs), and
    optionally {"notes": "..."}.
    """

    def post(self, request, pk, *args, **kwargs):
        self.require(request, 'make')

        plugin = _plugin()
        part = _part(pk)
        link = links.get_link(part)

        if not link:
            return _error('This part is not linked to a machine and its files')

        data = request.data if isinstance(request.data, dict) else {}

        try:
            if data.get('runs') not in (None, ''):
                runs = int(data['runs'])
            else:
                runs = logic.runs_for(
                    float(data.get('quantity') or 0), float(link['parts_per_run'])
                )
        except (TypeError, ValueError):
            return _error('Enter the number of runs or the quantity to make')

        build = jobs.create_job(
            plugin,
            part,
            runs,
            machines.get_machine(plugin, link.get('machine')),
            request.user,
            notes=str(data.get('notes') or ''),
        )

        return Response(
            {
                'job': jobs.describe(build),
                **_part_out(plugin, part),
                'permissions': user_permissions(request.user),
            },
            status=status.HTTP_201_CREATED,
        )


def _job(pk: int):
    build = jobs.get_job(pk)

    if build is None:
        raise NotFound('Job not found')

    return build


class JobView(WorkshopView):
    """GET /plugin/workshop/job/<build id>/ - one job."""

    def get(self, request, pk, *args, **kwargs):
        return Response({'job': jobs.describe(_job(pk))})


class JobFileView(WorkshopView):
    """GET /plugin/workshop/job/<build id>/file/<attachment>/ - one file of a job."""

    def get(self, request, pk, attachment, *args, **kwargs):
        build = _job(pk)
        meta = jobs.job_meta(build) or {}

        if attachment not in [entry.get('attachment') for entry in meta.get('files') or []]:
            raise NotFound('This file does not belong to the job')

        found = links.get_attachment(build.part, attachment)

        if found is None:
            raise NotFound('This file of the job is no longer attached to the part')

        return _download(found)


class JobDownloadView(WorkshopView):
    """GET /plugin/workshop/job/<build id>/download/ - the files of a job: the file, or a zip."""

    def get(self, request, pk, *args, **kwargs):
        build = _job(pk)
        meta = jobs.job_meta(build) or {}

        return _download_set(build.part, meta.get('files') or [], f'{build.reference}-files')


class JobActionView(WorkshopView):
    """POST /plugin/workshop/job/<build id>/<action>/

    book    book what was made into stock
            {"good": 38, "runs": 2, "location": 7, "notes": "", "finish": false,
             "material": [{"line": 91, "quantity": 2}]}
            'material' may be left out: the runs then use what the bill of
            materials says. 'finish' closes the job even if it is short.
    close   complete the build order as it stands
    cancel  cancel a job which has nothing in stock
    """

    def post(self, request, pk, action, *args, **kwargs):
        self.require(request, 'manage')

        plugin = _plugin()
        build = _job(pk)
        data = request.data if isinstance(request.data, dict) else {}
        result: dict = {}

        if action == 'book':
            from stock.models import StockLocation

            location = None

            if data.get('location'):
                location = StockLocation.objects.filter(pk=data['location']).first()

                if location is None:
                    return _error('This stock location does not exist')

            material = data.get('material')

            if material is not None and not isinstance(material, list):
                return _error('The material used is not in the form the plugin expects')

            result = jobs.book(
                plugin,
                build,
                data.get('good'),
                data.get('runs'),
                request.user,
                location=location,
                notes=str(data.get('notes') or '')[: jobs.NOTE_LIMIT],
                material=material,
                finish=bool(data.get('finish')),
            )

        elif action == 'close':
            result = {'closed': jobs.close(build, request.user)}

        elif action == 'cancel':
            result = jobs.cancel(build, request.user)

        else:
            raise NotFound('Unknown action')

        build.refresh_from_db()

        return Response({
            'result': result,
            'job': jobs.describe(build),
            **_part_out(plugin, build.part),
            'permissions': user_permissions(request.user),
        })


class OverviewView(WorkshopView):
    """GET /plugin/workshop/overview/ - every machine, linked part and open job."""

    def get(self, request, *args, **kwargs):
        plugin = _plugin()
        include_pending = plugin.include_pending()
        open_jobs = jobs.active_jobs()
        known = {machine['id']: machine for machine in machines.list_machines(plugin)}

        by_part: dict = {}

        for build in open_jobs:
            by_part.setdefault(build.part_id, []).append(build)

        parts = []

        for part in links.linked_parts():
            link = links.get_link(part)

            if not link:
                continue

            numbers = planning.part_numbers(part, include_pending)

            parts.append({
                'part': _part_label(part),
                'link': _link_out(plugin, part, link, known=known),
                'numbers': numbers,
                'suggestion': planning.suggestion(link, numbers),
                'open_jobs': len(by_part.get(part.pk, [])),
            })

        return Response({
            'machines': _machines_out(plugin),
            'parts': parts,
            'jobs': [jobs.describe(build) for build in reversed(open_jobs)],
            'history': [
                jobs.describe(build) for build in jobs.recent_jobs(limit=15, finished_only=True)
            ],
            'include_pending': include_pending,
            'permissions': user_permissions(request.user),
        })
