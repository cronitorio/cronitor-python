import os
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from datetime import datetime

from cronitor import ping, Monitor
import cronitor

FAKE_API_KEY = 'fake-api-key'
FAKE_ID = 'd3x0c1'

FAKE_MONITOR = {
    'name': 'A Test Key',
    'key': 'a-test_key',
    'rules': [{
        'rule_type': 'not_on_schedule',
        'value': '* * * * *'
    }],
    'id': FAKE_ID
}

class MonitorTests(unittest.TestCase):

    def setUp(self):
        Monitor.api_key = FAKE_API_KEY

    def tearDown(self):
        pass

    def test_requires_monitor_id_or_key_or_data(self):
        self.assertRaises(cronitor.InvalidMonitorParams, lambda: Monitor())

    @patch('cronitor.Monitor._create', return_value=FAKE_MONITOR)
    def test_create_monitor_with_schedule(self, mocked_create):
        self.monitor = Monitor.create(schedule=FAKE_MONITOR['rules'][0]['value'])
        self.assertEqual(self.monitor.data.key, FAKE_MONITOR['key'])
        self.assertEqual(self.monitor.data.rules[0]['rule_type'], 'not_on_schedule')
        self.assertEqual(self.monitor.data.rules[0]['value'], FAKE_MONITOR['rules'][0]['value'])

    @patch('requests.post')
    def test_create_monitor_fails(self, mocked_post):
        mocked_post.return_value.status_code = 400
        with self.assertRaises(cronitor.MonitorNotCreated):
             Monitor.create(data={'name': 'What UP!!!'})


    @patch('requests.get')
    def test_get_monitor_invalid_code(self, mocked_get):
        mocked_get.return_value.status_code = 404
        with self.assertRaises(cronitor.MonitorNotFound):
             Monitor.get("I don't exist")


    @patch('cronitor.Monitor._create', return_value=FAKE_MONITOR)
    @patch('requests.get')
    def test_get_or_create_monitor_with_schedule(self, mocked_get, mocked_create):
        mocked_get.return_value.status_code = 404
        self.monitor = Monitor.get_or_create("Foo", schedule=FAKE_MONITOR['rules'][0]['value'])
        self.assertEqual(self.monitor.data.key, FAKE_MONITOR['key'])
        self.assertEqual(self.monitor.data.rules[0]['rule_type'], 'not_on_schedule')
        self.assertEqual(self.monitor.data.rules[0]['value'], FAKE_MONITOR['rules'][0]['value'])

    @patch('cronitor.Monitor._create', return_value=FAKE_MONITOR)
    @patch('requests.get')
    def test_get_or_create_monitor_with_schedule(self, mocked_get, mocked_create):
        mocked_get.return_value.status_code = 404
        self.monitor = Monitor.get_or_create("Foo", schedule=FAKE_MONITOR['rules'][0]['value'])
        assert mocked_create.called
        assert self.monitor.data.key == FAKE_MONITOR['key']
        assert self.monitor.data.rules[0]['rule_type'] == 'not_on_schedule'
        assert self.monitor.data.rules[0]['value'] == FAKE_MONITOR['rules'][0]['value']

    @patch('requests.put')
    @patch('cronitor.Monitor._fetch')
    def test_update_monitor_fails_validation(self, mocked_fetch, mocked_update):
        mocked_fetch.return_value = FAKE_MONITOR
        mocked_update.return_value.status_code = 400
        monitor = Monitor(FAKE_ID)
        with self.assertRaises(cronitor.MonitorNotUpdated):
            monitor.update(name='')

    @patch('requests.delete')
    def test_delete_no_id(self, mocked_delete):
        mocked_delete.return_value.status_code = 204
        monitor = Monitor(FAKE_ID)
        monitor.delete()


class PingDecoratorTests(unittest.TestCase):

    @patch('cronitor.Monitor')
    def test_ping_wraps_function_success(self, mocked_class):
        mocked_instance = mocked_class.return_value
        self.function_call()
        assert mocked_instance.run.called
        assert mocked_instance.complete.called

    @patch('cronitor.Monitor')
    def test_ping_wraps_function_raises_exception(self, mocked_class):
        mocked_instance = mocked_class.return_value
        self.assertRaises(Exception, lambda: self.error_function_call())
        assert mocked_instance.run.called
        assert mocked_instance.fail.called


    @ping('Python Ping Decorator Test', schedule="* * * * *")
    def function_call(self):
        return

    @ping('Python Ping Decorator Test', schedule="* * * * *")
    def error_function_call(self):
        raise Exception
