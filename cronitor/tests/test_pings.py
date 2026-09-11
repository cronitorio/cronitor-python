import os
import unittest
from unittest.mock import patch, ANY, call
import cronitor
import pytest

# a reserved monitorkey for running integration tests against cronitor.link
FAKE_KEY = 'd3x0c1'
FAKE_API_KEY = 'ping-api-key'

class MonitorPingTests(unittest.TestCase):

    def setUp(self):
        cronitor.api_key = FAKE_API_KEY

    def test_endpoints(self):
        monitor = cronitor.Monitor(key=FAKE_KEY)

        self.assertTrue(monitor.ping())

        states = ['run', 'complete', 'fail', 'ok']
        for state in states:
            self.assertTrue(monitor.ping(state=state))


    @patch('cronitor.Monitor._req.get')
    def test_with_all_params(self, ping):

        monitor = cronitor.Monitor(FAKE_KEY, env='staging')

        params = {
            'state': 'run',
            'host': 'foo',
            'message': 'test message',
            'series': 'abc',
            'metrics': {
                'duration': 100,
                'count': 5,
                'error_count':2
            }
        }

        monitor.ping(**params)
        del params['metrics']
        params['metric'] = [ANY, ANY, ANY,]
        params['env'] = monitor.env
        params['stamp'] = ANY

        ping.assert_called_once_with(
            headers={
                'User-Agent': 'cronitor-python',
            },
            params=params,
            timeout=5,
            url='https://cronitor.link/p/{}/{}'.format(FAKE_API_KEY, FAKE_KEY))


    def test_convert_metrics_hash(self):
        monitor = cronitor.Monitor(FAKE_KEY)
        clean = monitor._clean_params({ 'metrics': {
            'duration': 100,
            'count': 500,
            'error_count': 20
        }})
        self.assertListEqual(sorted(clean['metric']), sorted(['count:500', 'duration:100', 'error_count:20' ]))

    def test_clean_params_custom_metrics(self):
        monitor = cronitor.Monitor(FAKE_KEY)
        clean = monitor._clean_params({'metrics': {
            'queue_depth': 42,
            'quality_score': 0.87,
            'retry-count': 3,
        }})
        self.assertCountEqual(clean['metric'], [
            'queue_depth:42',
            'quality_score:0.87',
            'retry-count:3',
        ])

    def test_clean_params_metric_numeric_edges(self):
        monitor = cronitor.Monitor(FAKE_KEY)
        clean = monitor._clean_params({'metrics': {
            'empty_batch': 0,
            'offset': -3,
            'quality_score': 0.87,
            'duration': 1.5,
        }})
        self.assertCountEqual(clean['metric'], [
            'empty_batch:0',
            'offset:-3',
            'quality_score:0.87',
            'duration:1.5',
        ])

    def test_clean_params_does_not_truncate_or_reject_names(self):
        # Server is the authority: the SDK encodes names as given (never truncates).
        long_name = 'a' * 64
        monitor = cronitor.Monitor(FAKE_KEY)
        clean = monitor._clean_params({'metrics': {long_name: 1, 'bad name': 2}})
        self.assertCountEqual(clean['metric'], [long_name + ':1', 'bad name:2'])

    def test_clean_params_mixed_builtin_and_custom_metrics(self):
        monitor = cronitor.Monitor(FAKE_KEY)
        clean = monitor._clean_params({'metrics': {
            'count': 10,
            'queue_depth': 42,
            'error_count': 0,
            'quality_score': 0.5,
        }})
        self.assertCountEqual(clean['metric'], [
            'count:10',
            'queue_depth:42',
            'error_count:0',
            'quality_score:0.5',
        ])

    @patch('cronitor.Monitor._req.get')
    def test_ping_encodes_custom_metrics(self, ping):
        monitor = cronitor.Monitor(FAKE_KEY)
        monitor.ping(state='complete', metrics={
            'queue_depth': 42,
            'quality_score': 0.87,
            'offset': -1,
            'empty_batch': 0,
        })
        params = ping.call_args[1]['params']
        self.assertCountEqual(params['metric'], [
            'queue_depth:42',
            'quality_score:0.87',
            'offset:-1',
            'empty_batch:0',
        ])


class PingDecoratorTests(unittest.TestCase):

    def setUp(self):
        cronitor.api_key = FAKE_API_KEY

    @patch('cronitor.Monitor.ping')
    def test_ping_wraps_function_success(self, mocked_ping):
        calls = [call(state='run', series=ANY), call(state='complete', series=ANY, metrics={'duration': ANY}, message=ANY)]
        self.function_call()
        mocked_ping.assert_has_calls(calls)

    @patch('cronitor.Monitor.ping')
    def test_ping_wraps_function_raises_exception(self, mocked_ping):
        calls = [call(state='run', series=ANY), call(state='fail', series=ANY, metrics={'duration': ANY}, message=ANY)]
        self.assertRaises(Exception, lambda: self.error_function_call())
        mocked_ping.assert_has_calls(calls)


    @patch('cronitor.Monitor.ping')
    @patch('cronitor.Monitor.__init__')
    def test_ping_with_non_default_env(self, mocked_monitor, mocked_ping):
        mocked_monitor.return_value = None
        self.staging_env_function_call()
        mocked_monitor.assert_has_calls([call('ping-decorator-test', env='staging')])

    @cronitor.job('ping-decorator-test')
    def function_call(self):
        return

    @cronitor.job('ping-decorator-test')
    def error_function_call(self):
        raise Exception

    @cronitor.job('ping-decorator-test', env='staging')
    def staging_env_function_call(self):
        return




