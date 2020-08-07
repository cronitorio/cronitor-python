import os
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from cronitor.monitor import Monitor

class UnitTests(unittest.TestCase):

    def setUp(self):
        self.monitor = Monitor(id='d3x0c1')

    def test_run(self):
        resp = self.monitor.run()
        self.assertEqual(resp.status_code, 200)
