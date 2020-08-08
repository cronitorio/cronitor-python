import os
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from cronitor import ping
import cronitor

cronitor.api_key = 'cb54ac4fd16142469f2d84fc1bbebd84XXXDEADXXX'

class MonitorPingTests(unittest.TestCase):

    def setUp(self):
        self.monitor = cronitor.Monitor(id='bN3pas')

    def test_run(self):
        resp = self.monitor.run()
        self.assertEqual(resp.status_code, 200)


class PingDecoratorTests(unittest.TestCase):

    MONITOR_NAME = 'DECORATED METHOD MONITOR'

    def test_ping_wraps_function(self):
        self.function_call("Maybe!")
        monitor = cronitor.Monitor.get(self.MONITOR_NAME)
        self.assertEqual(monitor.data.name, self.MONITOR_NAME)


    @ping(MONITOR_NAME, schedule="* * * * *")
    def function_call(self, message):
        return "Call me {}".format(message)