import os
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from cronitor import ping, Monitor
import cronitor

cronitor.api_key = os.environ.get("CRONITOR_API_KEY", None)

class MonitorTest(unittest.TestCase):

    def setUp(self):
        self.monitor = None

    def tearDown(self):
        if self.monitor: self.monitor.delete()

    def test_requires_monitor_id(self):
        self.assertRaises(cronitor.MonitorNotFound, lambda: Monitor())

    def test_get_or_create(self):
        name = 'Test Get Or Create - Python'
        schedule = '* * * * *'
        self.monitor = Monitor.get_or_create(name=name, schedule=schedule)
        self.assertEqual(self.monitor.data.name, name)
        self.assertEqual(self.monitor.data.rules[0]['rule_type'], 'not_on_schedule')
        self.assertEqual(self.monitor.data.rules[0]['value'], schedule)

        # does not create second monitor with same name
        _monitor = Monitor.get_or_create(name=name, schedule=schedule)
        self.assertEqual(_monitor.id, self.monitor.id)

    def test_get_or_create(self):
        name = 'Test Get Or Create - Python'
        self.monitor = Monitor.get_or_create(name=name, rules=[{'rule_type': 'not_on_schedule', 'value': '* * * * *'}])
        self.assertEqual(self.monitor.data.name, name)
        self.assertEqual(self.monitor.data.rules[0]['rule_type'], 'not_on_schedule')
        self.assertEqual(self.monitor.data.rules[0]['value'], '* * * * *')

    def test_get_or_create_fails_no_name(self):
        self.assertRaises(cronitor.MonitorNotCreated, lambda: Monitor.get_or_create())

    def test_update_modifies_data(self):
        self.monitor = Monitor.create(name="Updatable Monitor")
        self.assertEqual(len(self.monitor.data.rules), 0)
        self.monitor.update(rules=[{'rule_type': 'not_on_schedule', 'value': '* * * * *'}])
        self.assertEqual(len(self.monitor.data.rules), 1)


class PingDecoratorTests(unittest.TestCase):
    MONITOR_NAME = 'Created By Python Ping Decorator'

    def setUp(self):
        self.monitor = None

    def tearDown(self):
        self.monitor.delete()

    def test_ping_wraps_function(self):
        self.function_call()
        self.monitor = cronitor.Monitor.get(self.MONITOR_NAME)
        self.assertEqual(self.monitor.data.name, self.MONITOR_NAME)
        self.assertTrue(self.monitor.data.initialized)
        self.assertTrue(self.monitor.data.passing)


    @ping(MONITOR_NAME, schedule="* * * * *")
    def function_call(self):
        return True