"""Workshop plugin for InvenTree.

For parts which are made in-house on a machine from a file: cut on a laser,
milled on a desktop CNC, and so on. The files are kept as attachments of the
part, with the machine which runs them and how many parts one run gives. A
job is an InvenTree build order: somebody takes the files, sets the machine
up and runs it, then books the good parts into stock from here.

Nothing is sent to any machine.
"""

import logging

from plugin import InvenTreePlugin
from plugin.mixins import SettingsMixin, UrlsMixin, UserInterfaceMixin

from . import PLUGIN_VERSION

logger = logging.getLogger('inventree')

# Compiled frontend: a single file which exports every entry point
FRONTEND = 'Workshop.js'

SLUG = 'workshop'


class WorkshopPlugin(SettingsMixin, UrlsMixin, UserInterfaceMixin, InvenTreePlugin):
    """Jobs for parts which are made in-house on a laser, a CNC mill or another machine."""

    # Plugin metadata
    TITLE = 'Workshop Jobs'
    NAME = 'Workshop'
    SLUG = SLUG
    DESCRIPTION = 'Keep the machine files of in-house parts on the parts they make, and book runs of the laser or CNC into stock as build orders'
    VERSION = PLUGIN_VERSION

    AUTHOR = 'EdgeMachines'
    WEBSITE = 'https://github.com/nemccarthy/inventree-workshop'
    LICENSE = 'MIT'

    # Developed and tested against InvenTree 1.7.3
    MIN_VERSION = '1.7.0'

    SETTINGS = {
        'COUNT_PENDING_BUILDS': {
            'name': 'Count pending build orders',
            'description': 'When working out whether more of a part should be made, also count the requirements of build orders which have not been issued yet',
            'validator': bool,
            'default': False,
        },
        'LEAD_DAYS': {
            'name': 'Days until parts are in stock',
            'description': 'Target date of the build order of a job, in days from the day it is raised',
            'validator': int,
            'default': 1,
        },
        'DEFAULT_LOCATION': {
            'name': 'Stock location for finished parts',
            'description': 'Where parts are booked into stock, when neither the link nor the part has a default location',
            'model': 'stock.stocklocation',
            'default': '',
        },
        'SHOW_NAVIGATION': {
            'name': 'Show in the navigation bar',
            'description': 'Add a Workshop link to the main navigation bar',
            'validator': bool,
            'default': True,
        },
        'SHOW_PART_PANEL': {
            'name': 'Show on part pages',
            'description': 'Add a Workshop panel to part pages',
            'validator': bool,
            'default': True,
        },
        'PANEL_LINKED_ONLY': {
            'name': 'Only on linked parts',
            'description': 'Show the Workshop panel only on parts which are linked to a machine. New parts are then linked from the Workshop page',
            'validator': bool,
            'default': False,
        },
    }

    # Helpers used by the rest of the plugin

    def int_setting(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get_setting(key))
        except (TypeError, ValueError):
            return default

    def default_location(self):
        """The stock location from the plugin settings, or None."""
        from stock.models import StockLocation

        value = self.get_setting('DEFAULT_LOCATION')

        try:
            return StockLocation.objects.filter(pk=int(value)).first()
        except (TypeError, ValueError):
            return None

    def include_pending(self) -> bool:
        return bool(self.get_setting('COUNT_PENDING_BUILDS'))

    # Custom URL endpoints (from UrlsMixin), served below /plugin/workshop/

    def setup_urls(self):
        """Register the API endpoints."""
        from django.urls import path

        from . import views

        return [
            path('overview/', views.OverviewView.as_view(), name='workshop-overview'),
            path('machines/', views.MachinesView.as_view(), name='workshop-machines'),
            path('machines/<int:pk>/', views.MachineView.as_view(), name='workshop-machine'),
            path('part/<int:pk>/', views.PartView.as_view(), name='workshop-part'),
            path('part/<int:pk>/files/', views.FilesView.as_view(), name='workshop-files'),
            path(
                'part/<int:pk>/file/<int:attachment>/',
                views.PartFileView.as_view(),
                name='workshop-part-file',
            ),
            path('part/<int:pk>/download/', views.PartDownloadView.as_view(), name='workshop-download'),
            path('part/<int:pk>/preview/', views.PreviewView.as_view(), name='workshop-preview'),
            path('part/<int:pk>/make/', views.MakeView.as_view(), name='workshop-make'),
            path('job/<int:pk>/', views.JobView.as_view(), name='workshop-job'),
            path(
                'job/<int:pk>/file/<int:attachment>/',
                views.JobFileView.as_view(),
                name='workshop-job-file',
            ),
            path('job/<int:pk>/download/', views.JobDownloadView.as_view(), name='workshop-job-download'),
            path(
                'job/<int:pk>/<str:action>/',
                views.JobActionView.as_view(),
                name='workshop-job-action',
            ),
        ]

    # User interface (from UserInterfaceMixin)

    @staticmethod
    def _can_view(request) -> bool:
        from users.permissions import check_user_role

        user = getattr(request, 'user', None)

        return bool(user and check_user_role(user, 'part', 'view'))

    def get_ui_routes(self, request, context, **kwargs):
        """The Workshop page, at /web/plugin/workshop/jobs."""
        return [
            {
                'key': 'workshop-jobs',
                'title': 'Workshop',
                'source': self.plugin_static_file(f'{FRONTEND}:renderWorkshopPage'),
                'options': {'path': 'jobs'},
            }
        ]

    def get_ui_navigation_items(self, request, context, **kwargs):
        """A link to the Workshop page in the main navigation bar."""
        if not self.get_setting('SHOW_NAVIGATION') or not self._can_view(request):
            return []

        return [
            {
                'key': 'workshop-jobs',
                'title': 'Workshop',
                'icon': 'ti:tools:outline',
                'options': {'url': f'plugin/{self.SLUG}/jobs'},
            }
        ]

    def get_ui_panels(self, request, context: dict, **kwargs):
        """Add the Workshop panel to part pages."""
        context = context or {}

        if context.get('target_model') != 'part':
            return []

        if not self.get_setting('SHOW_PART_PANEL') or not self._can_view(request):
            return []

        try:
            part_id = int(context.get('target_id'))
        except (TypeError, ValueError):
            return []

        if self.get_setting('PANEL_LINKED_ONLY'):
            from part.models import Part

            from .links import get_link

            part = Part.objects.filter(pk=part_id).first()

            if part is None or get_link(part) is None:
                return []

        return [
            {
                'key': 'workshop',
                'title': 'Workshop',
                'description': 'Make this part on a workshop machine',
                'icon': 'ti:tools:outline',
                'source': self.plugin_static_file(f'{FRONTEND}:renderWorkshopPartPanel'),
                'context': {'part_id': part_id, 'slug': self.SLUG},
            }
        ]
