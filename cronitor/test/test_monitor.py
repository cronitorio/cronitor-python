import os
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from cronitor import ping
import cronitor

cronitor.api_key = os.environ.get("CRONITOR_API_KEY", None)

class MonitorTest(unittest.TestCase):
    def test_requires_monitor_id(self):
        pass

    def test_get_or_create(self):
        pass

    def test_update(self):
        pass

    def test_delete(self):
        pass

    def test_data_access(self):
        pass

    def test_set_data(self):
        pass

    def test_payload(self):
        pass


class PingDecoratorTests(unittest.TestCase):
    MONITOR_NAME = 'Created By Ping Decorator'

    def tearDown(self):
        monitor = cronitor.Monitor.get(self.MONITOR_NAME)
        # monitor.delete()

    def test_ping_wraps_function(self):
        self.function_call()
        monitor = cronitor.Monitor.get(self.MONITOR_NAME)
        self.assertEqual(monitor.data.name, self.MONITOR_NAME)
        self.assertTrue(monitor.data.initialized)
        self.assertTrue(monitor.data.passing)


    @ping(MONITOR_NAME, schedule="* * * * *")
    def function_call(self):
        return True