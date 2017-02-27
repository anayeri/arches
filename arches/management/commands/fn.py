'''
ARCHES - a program developed to inventory and manage immovable cultural heritage.
Copyright (C) 2013 J. Paul Getty Trust and World Monuments Fund

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
'''

"""This module contains commands for building Arches."""

import os
from arches.management.commands import utils
from arches.app.models import models
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """
    Commands for running common elasticsearch commands

    """

    def add_arguments(self, parser):
        parser.add_argument('operation', nargs='?')

        parser.add_argument('-s', '--source', action='store', dest='fn_source', default='',
            help='Function file to be loaded')

        parser.add_argument('-n', '--name', action='store', dest='fn_name', default='',
            help='The name of the function to unregister')

    def handle(self, *args, **options):
        if options['operation'] == 'register':
            self.register(source_dir=options['fn_source'])

        if options['operation'] == 'unregister':
            self.unregister(fn_name=options['fn_name'])

    def start(self, dest_dir):
        """
        Creates a template function

        """

    def register(self, source_dir):
        """
        Inserts a function into the arches db

        """

        fn = models.Function(
            name = "Sample Function",
            functiontype = "node",
            description = "Just a sample",
            defaultconfig = "{}",
            modulename = os.path.basename(source_dir),
            classname = "SampleFunction",
            component = os.path.splitext(os.path.basename(source_dir))[0] + '.js'
        )
        fn.save()
        # with (open_source, 'r') as f:

    def unregister(self, fn_name):
        """
        Removes a function from the system

        """
        try:
            fn = models.Function.objects.filter(name=fn_name)
            fn[0].delete()
        except Exception as e:
            print e


    def validate(self):
        """
        Validates a functions configuration

        """
