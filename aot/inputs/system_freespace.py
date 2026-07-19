# coding=utf-8
import copy
import os

from aot.inputs.base_input import AbstractInput

# Measurements
measurements_dict = {
    0: {
        'measurement': 'disk_space',
        'unit': 'MB'
    }
}

# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'RPiFreeSpace',
    'input_manufacturer': 'AoT',
    'input_name': 'Free Space',
    'input_library': 'os.statvfs()',
    'measurements_name': 'Unallocated Disk Space',
    'measurements_dict': measurements_dict,

    'options_enabled': [
        'location',
        'period'
    ],

    'location': {
        'title': 'Path',
        'phrase': 'The path to monitor the free space of',
        'options': [('/', '')]
    }
}


class InputModule(AbstractInput):
    """Monitors unallocated disk space of a filesystem path in MB."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.path = None

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.path = self.input_dev.location

    def get_measurement(self):
        """Gets the free space"""
        if not self.path:
            self.logger.error("Error 101: Device not set up. See https://aot-inc.github.io/AoT/Error-Codes#error-101 for more info.")
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        f = os.statvfs(self.path)
        self.value_set(0, (f.f_bsize * f.f_bavail) / 1000000.0)

        return self.return_dict
