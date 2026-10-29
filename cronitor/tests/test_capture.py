import json
import logging
import os
import re
import socket
import sys
import time
import unittest

import requests
from unittest.mock import patch

import cronitor
from cronitor import ingest
from cronitor.tests.envelope_parser import RecordingSend

FAKE_API_KEY = 'capture-api-key'
HEX32 = re.compile(r'^[0-9a-f]{32}$')
RFC3339_UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$')
FRAME_KEYS = {'filename', 'abs_path', 'function', 'module', 'lineno',
              'context_line', 'pre_context', 'post_context', 'in_app'}


def _inner():
    raise ValueError('inner boom')


def _outer():
    try:
        _inner()
    except ValueError as e:
        raise RuntimeError('outer boom') from e


def _attr(record, name):
    return record['attributes'][name]


class CaptureTestCase(unittest.TestCase):
    """Installs a recording transport and known settings for each test."""

    def setUp(self):
        self._saved = {name: getattr(cronitor, name) for name in
                       ('api_key', 'ingest_url', 'environment', 'release', 'capture_exceptions')}
        cronitor.api_key = FAKE_API_KEY
        cronitor.ingest_url = ingest.DEFAULT_INGEST_URL
        cronitor.environment = None
        cronitor.release = None
        cronitor.capture_exceptions = True
        self.send = RecordingSend()
        self._previous_transport = ingest.set_transport(ingest.Transport(send=self.send))

    def tearDown(self):
        ingest.set_transport(self._previous_transport)
        for name, value in self._saved.items():
            setattr(cronitor, name, value)

    def flushed_events(self):
        self.assertTrue(cronitor.flush(2.0))
        return self.send.events()

    def flushed_logs(self):
        self.assertTrue(cronitor.flush(2.0))
        return self.send.log_records()

    def only_event(self):
        events = self.flushed_events()
        self.assertEqual(len(events), 1, events)
        return events[0]


class CaptureExceptionTests(CaptureTestCase):

    def test_chained_cause_is_two_values_oldest_first(self):
        try:
            _outer()
        except RuntimeError as e:
            event_id = cronitor.capture_exception(e)

        self.assertRegex(event_id, HEX32)
        self.assertTrue(cronitor.flush(2.0))
        header, items = self.send.envelopes()[0]
        self.assertEqual(header['event_id'], event_id)
        self.assertEqual([h['type'] for h, _ in items], ['event'])
        event = items[0][1]
        self.assertEqual(event['event_id'], event_id)

        values = event['exception']['values']
        self.assertEqual([v['type'] for v in values], ['ValueError', 'RuntimeError'])
        self.assertEqual([v['value'] for v in values], ['inner boom', 'outer boom'])
        self.assertEqual([v['module'] for v in values], [None, None])
        for value in values:
            self.assertEqual(value['mechanism'], {'type': 'generic', 'handled': True})

        cause_frames = values[0]['stacktrace']['frames']
        self.assertEqual([f['function'] for f in cause_frames], ['_outer', '_inner'])
        self.assertEqual(cause_frames[-1]['context_line'].strip(), "raise ValueError('inner boom')")
        self.assertEqual(cause_frames[-1]['pre_context'][-1].strip(), 'def _inner():')

        frames = values[1]['stacktrace']['frames']
        self.assertEqual([f['function'] for f in frames],
                         ['test_chained_cause_is_two_values_oldest_first', '_outer'])
        self.assertEqual(frames[-1]['context_line'].strip(), "raise RuntimeError('outer boom') from e")

        here = os.path.abspath(__file__)
        for frame in cause_frames + frames:
            self.assertEqual(set(frame), FRAME_KEYS)
            self.assertEqual(frame['abs_path'], here)
            self.assertEqual(frame['filename'], os.path.join('cronitor', 'tests', 'test_capture.py'))
            self.assertEqual(frame['module'], __name__)
            self.assertIsInstance(frame['lineno'], int)
            self.assertTrue(frame['in_app'])
            self.assertEqual(len(frame['pre_context']), 5)
            self.assertLessEqual(len(frame['post_context']), 5)
            self.assertNotIn('vars', frame)

    def test_implicit_context_is_chained(self):
        try:
            try:
                raise KeyError('first')
            except KeyError:
                raise TypeError('second')
        except TypeError as e:
            cronitor.capture_exception(e)
        values = self.only_event()['exception']['values']
        self.assertEqual([v['type'] for v in values], ['KeyError', 'TypeError'])

    def test_raise_from_none_suppresses_context(self):
        try:
            try:
                raise KeyError('first')
            except KeyError:
                raise TypeError('second') from None
        except TypeError as e:
            cronitor.capture_exception(e)
        values = self.only_event()['exception']['values']
        self.assertEqual([v['type'] for v in values], ['TypeError'])

    def test_custom_exception_module(self):
        try:
            raise cronitor.APIError('nope')
        except cronitor.APIError as e:
            cronitor.capture_exception(e)
        value = self.only_event()['exception']['values'][0]
        self.assertEqual(value['type'], 'APIError')
        self.assertEqual(value['module'], 'cronitor')

    def test_library_frames_are_not_in_app(self):
        try:
            json.loads('{not json')
        except ValueError as e:
            cronitor.capture_exception(e)
        frames = self.only_event()['exception']['values'][-1]['stacktrace']['frames']
        self.assertTrue(frames[0]['in_app'])
        self.assertTrue(frames[-1]['abs_path'].endswith(os.path.join('json', 'decoder.py')))
        self.assertFalse(frames[-1]['in_app'])
        self.assertEqual(frames[-1]['module'], 'json.decoder')

    def test_in_app_rules(self):
        from cronitor.capture import _in_app
        self.assertFalse(_in_app('/venv/lib/python3.8/site-packages/requests/api.py'))
        self.assertFalse(_in_app('/usr/lib/python3/dist-packages/yaml/__init__.py'))
        self.assertFalse(_in_app(json.__file__))
        self.assertFalse(_in_app('<frozen importlib._bootstrap>'))
        self.assertTrue(_in_app('/srv/app/jobs/nightly.py'))

    def test_defaults_to_current_exception(self):
        try:
            raise LookupError('current')
        except LookupError:
            event_id = cronitor.capture_exception()
        event = self.only_event()
        self.assertEqual(event['event_id'], event_id)
        self.assertEqual(event['exception']['values'][0]['type'], 'LookupError')

    def test_no_current_exception_sends_nothing(self):
        self.assertIsNone(cronitor.capture_exception())
        self.assertEqual(self.flushed_events(), [])

    def test_event_fields(self):
        cronitor.environment = 'production'
        cronitor.release = '1.2.3'
        try:
            raise ValueError('x')
        except ValueError as e:
            cronitor.capture_exception(e, level='fatal')
        event = self.only_event()
        self.assertRegex(event['timestamp'], RFC3339_UTC)
        self.assertEqual(event['platform'], 'python')
        self.assertEqual(event['level'], 'fatal')
        self.assertEqual(event['server_name'], socket.gethostname())
        self.assertEqual(event['environment'], 'production')
        self.assertEqual(event['release'], '1.2.3')
        self.assertEqual(event['sdk'], {'name': 'cronitor-python', 'version': ingest.SDK_VERSION})
        self.assertEqual(event['tags'], {})
        self.assertEqual(event['extra'], {})

    def test_optional_fields_omitted_when_unset(self):
        cronitor.capture_message('hello')
        event = self.only_event()
        self.assertNotIn('environment', event)
        self.assertNotIn('release', event)

    def test_value_is_truncated(self):
        try:
            raise ValueError('v' * 5000)
        except ValueError as e:
            cronitor.capture_exception(e)
        self.assertEqual(len(self.only_event()['exception']['values'][0]['value']), 4000)

    def test_deep_recursion_keeps_both_ends(self):
        def recurse(n):
            if n == 0:
                raise ValueError('bottom')
            return recurse(n - 1)
        try:
            recurse(300)
        except ValueError as e:
            cronitor.capture_exception(e)
        frames = self.only_event()['exception']['values'][0]['stacktrace']['frames']
        self.assertLessEqual(len(frames), 100)
        self.assertEqual(frames[0]['function'], 'test_deep_recursion_keeps_both_ends')
        self.assertEqual(frames[-1]['context_line'].strip(), "raise ValueError('bottom')")

    def test_not_an_exception_sends_nothing(self):
        with self.assertLogs('cronitor.capture', 'WARNING'):
            self.assertIsNone(cronitor.capture_exception('not an exception'))
        self.assertEqual(self.flushed_events(), [])

    def test_no_api_key_sends_nothing(self):
        cronitor.api_key = None
        try:
            raise ValueError('x')
        except ValueError as e:
            with self.assertLogs('cronitor.ingest', 'ERROR'):
                self.assertIsNone(cronitor.capture_exception(e))
        self.assertEqual(self.flushed_events(), [])

    def test_huge_extra_is_dropped_to_fit_the_size_limit(self):
        try:
            raise ValueError('x')
        except ValueError as e:
            event_id = cronitor.capture_exception(e, extra={'blob': 'x' * 2000000})
        self.assertRegex(event_id, HEX32)
        event = self.only_event()
        self.assertEqual(event['extra'], {'_trimmed': 'source context dropped; extra dropped: event over 900 KB'})
        frame = event['exception']['values'][0]['stacktrace']['frames'][-1]
        self.assertEqual(frame['context_line'].strip(), "raise ValueError('x')")
        self.assertNotIn('pre_context', frame)

    def test_many_chained_frames_are_trimmed_to_fit(self):
        def recurse(n, i):
            if n == 0:
                raise ValueError('bottom %d' % i)
            return recurse(n - 1, i)

        def chain(i):
            try:
                recurse(150, i)
            except ValueError as e:
                if i == 0:
                    raise
                try:
                    chain(i - 1)
                except ValueError as cause:
                    raise e from cause

        try:
            chain(9)
        except ValueError as e:
            # a real chain of short source lines stays well under 900 KB, so lower the limit
            with patch('cronitor.ingest.MAX_EVENT_BYTES', 60000):
                cronitor.capture_exception(e, extra={'batch': 42})
        self.assertTrue(cronitor.flush(2.0))
        item_header, event = self.send.items('event')[0]
        self.assertLessEqual(item_header['length'], 60000)
        values = event['exception']['values']
        self.assertEqual(len(values), 10)
        for value in values:
            frames = value['stacktrace']['frames']
            self.assertEqual(len(frames), 20)
            self.assertEqual(frames[-1]['context_line'].strip(), "raise ValueError('bottom %d' % i)")
        self.assertTrue(event['extra']['_trimmed'].startswith(
            'source context dropped; extra dropped; frames cut to the last 20 per exception'))


class CaptureMessageTests(CaptureTestCase):

    def test_message_event(self):
        event_id = cronitor.capture_message('disk almost full')
        self.assertTrue(cronitor.flush(2.0))
        header, items = self.send.envelopes()[0]
        self.assertEqual(header['event_id'], event_id)
        event = items[0][1]
        self.assertEqual(event['message'], {'formatted': 'disk almost full'})
        self.assertEqual(event['level'], 'info')
        self.assertNotIn('exception', event)

    def test_level_and_truncation(self):
        cronitor.capture_message('m' * 5000, level='warning')
        event = self.only_event()
        self.assertEqual(event['level'], 'warning')
        self.assertEqual(len(event['message']['formatted']), 4000)

    def test_tags_extra_and_bindings(self):
        cronitor.capture_message('hi', monitor='nightly-backup', series='run-1',
                                 tags={'region': 'us-east-1', 'attempt': 2}, extra={'rows': [1, 2], 'obj': object()})
        event = self.only_event()
        self.assertEqual(event['tags'], {
            'cronitor.monitor': 'nightly-backup',
            'cronitor.series': 'run-1',
            'region': 'us-east-1',
            'attempt': '2',
        })
        self.assertEqual(event['extra']['rows'], [1, 2])
        self.assertTrue(event['extra']['obj'].startswith('<object object'))

    def test_extra_with_non_finite_floats_and_cycles_is_valid_json(self):
        circular = {'name': 'loop'}
        circular['self'] = circular
        cronitor.capture_message('hi', extra={'ratio': float('nan'), 'nested': {'limit': float('-inf')},
                                              'circular': circular, 'pairs': {(1, 2): 'tuple key', 'ok': 1}})
        extra = self.only_event()['extra']  # the strict reference parser rejects NaN
        self.assertEqual(extra['ratio'], 'nan')
        self.assertEqual(extra['nested'], {'limit': '-inf'})
        self.assertEqual(extra['circular']['name'], 'loop')
        self.assertEqual(extra['pairs'], {'ok': 1})

    def test_binding_tags_from_tags_dict(self):
        cronitor.capture_message('hi', tags={'cronitor.monitor': 'from-tags'})
        self.assertEqual(self.only_event()['tags'], {'cronitor.monitor': 'from-tags'})

    def test_tags_are_capped_and_bindings_kept(self):
        tags = {'t%02d' % i: 'v' for i in range(80)}
        tags['long'] = 'x' * 1000
        tags['k' * 100] = 'y'
        cronitor.capture_message('hi', monitor='m', series='s', tags=tags)
        event_tags = self.only_event()['tags']
        self.assertEqual(len(event_tags), 50)
        self.assertEqual(event_tags['cronitor.monitor'], 'm')
        self.assertEqual(event_tags['cronitor.series'], 's')
        self.assertTrue(all(len(k) <= 64 and len(v) <= 400 for k, v in event_tags.items()))


class MonitorCaptureTests(CaptureTestCase):

    def test_monitor_capture_exception_binds_key_env_and_api_key(self):
        monitor = cronitor.Monitor('nightly-backup', env='staging', api_key='monitor-key')
        try:
            raise ValueError('x')
        except ValueError:
            event_id = monitor.capture_exception(series='abc', tags={'a': 'b'})
        event = self.only_event()
        self.assertEqual(event['event_id'], event_id)
        self.assertEqual(event['environment'], 'staging')
        self.assertEqual(event['tags'], {'cronitor.monitor': 'nightly-backup', 'cronitor.series': 'abc', 'a': 'b'})
        self.assertIn('sentry_key=monitor-key,', self.send.calls[0].headers['X-Sentry-Auth'])

    def test_monitor_capture_message(self):
        cronitor.environment = 'production'
        cronitor.Monitor('heartbeat').capture_message('checked in', level='warning')
        event = self.only_event()
        self.assertEqual(event['message'], {'formatted': 'checked in'})
        self.assertEqual(event['level'], 'warning')
        self.assertEqual(event['environment'], 'production')
        self.assertEqual(event['tags'], {'cronitor.monitor': 'heartbeat'})


class LoggerTests(CaptureTestCase):

    def test_template_and_parameters(self):
        before = time.time()
        cronitor.environment = 'production'
        cronitor.logger.info('processed {count} rows for {name}', count=5, name='bob')
        self.assertTrue(cronitor.flush(2.0))
        header, items = self.send.envelopes()[0]
        self.assertNotIn('event_id', header)
        self.assertEqual(items[0][0]['type'], 'log')
        record = items[0][1]['items'][0]
        self.assertEqual(record['body'], 'processed 5 rows for bob')
        self.assertEqual(record['level'], 'info')
        self.assertIsInstance(record['timestamp'], float)
        self.assertGreaterEqual(record['timestamp'], before)
        self.assertEqual(record['attributes'], {
            'sentry.message.template': {'value': 'processed {count} rows for {name}', 'type': 'string'},
            'sentry.message.parameter.count': {'value': 5, 'type': 'integer'},
            'sentry.message.parameter.name': {'value': 'bob', 'type': 'string'},
            'sentry.severity_number': {'value': 9, 'type': 'integer'},
            'sentry.severity_text': {'value': 'info', 'type': 'string'},
            'sentry.sdk.name': {'value': 'cronitor-python', 'type': 'string'},
            'sentry.sdk.version': {'value': ingest.SDK_VERSION, 'type': 'string'},
            'sentry.environment': {'value': 'production', 'type': 'string'},
            'server.address': {'value': socket.gethostname(), 'type': 'string'},
        })

    def test_levels(self):
        for method in ('trace', 'debug', 'info', 'warning', 'error', 'fatal'):
            getattr(cronitor.logger, method)('a %s line' % method)
        records = self.flushed_logs()
        self.assertEqual([r['level'] for r in records], ['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
        self.assertEqual([_attr(r, 'sentry.severity_number')['value'] for r in records], [1, 5, 9, 13, 17, 21])
        self.assertEqual([_attr(r, 'sentry.severity_text')['value'] for r in records],
                         ['trace', 'debug', 'info', 'warn', 'error', 'fatal'])

    def test_braces_without_attributes_are_not_formatted(self):
        cronitor.logger.info('literal {braces}')
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], 'literal {braces}')
        self.assertNotIn('sentry.message.template', record['attributes'])

    def test_attributes_without_braces_are_plain_attributes(self):
        cronitor.logger.info('plain', user_id=3, ok=True, ratio=0.5, items=[1])
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], 'plain')
        self.assertNotIn('sentry.message.template', record['attributes'])
        self.assertEqual(_attr(record, 'user_id'), {'value': 3, 'type': 'integer'})
        self.assertEqual(_attr(record, 'ok'), {'value': True, 'type': 'boolean'})
        self.assertEqual(_attr(record, 'ratio'), {'value': 0.5, 'type': 'double'})
        self.assertEqual(_attr(record, 'items'), {'value': '[1]', 'type': 'string'})

    def test_non_finite_floats_are_sent_as_strings(self):
        cronitor.logger.info('ratios', nan=float('nan'), inf=float('inf'))
        self.assertTrue(cronitor.flush(2.0))
        raw = self.send.calls[0].envelope  # strict JSON: the parser below rejects NaN
        record = raw[1][0][1]['items'][0]
        self.assertEqual(_attr(record, 'nan'), {'value': 'nan', 'type': 'string'})
        self.assertEqual(_attr(record, 'inf'), {'value': 'inf', 'type': 'string'})

    def test_attributes_kwarg_like_sentry(self):
        cronitor.logger.warning('user {id} locked', id=7, attributes={'team': 'core'})
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], 'user 7 locked')
        self.assertEqual(_attr(record, 'team'), {'value': 'core', 'type': 'string'})
        self.assertEqual(_attr(record, 'sentry.message.parameter.id'), {'value': 7, 'type': 'integer'})

    def test_bad_template_keeps_body(self):
        cronitor.logger.error('{missing} key', other=1)
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], '{missing} key')
        self.assertEqual(_attr(record, 'other'), {'value': 1, 'type': 'integer'})

    def test_body_is_truncated(self):
        cronitor.logger.info('b' * 9000)
        self.assertEqual(len(self.flushed_logs()[0]['body']), 8000)

    def test_monitor_binding_attribute(self):
        cronitor.logger.info('bound', **{'cronitor.monitor': 'nightly', 'cronitor.series': 'r1'})
        record = self.flushed_logs()[0]
        self.assertEqual(_attr(record, 'cronitor.monitor'), {'value': 'nightly', 'type': 'string'})
        self.assertEqual(_attr(record, 'cronitor.series'), {'value': 'r1', 'type': 'string'})

    def test_attributes_are_capped(self):
        cronitor.logger.info('many', **{'a%02d' % i: i for i in range(80)})
        record = self.flushed_logs()[0]
        self.assertEqual(len(record['attributes']), 50)
        self.assertIn('sentry.severity_number', record['attributes'])

    def test_attribute_keys_and_values_are_capped(self):
        cronitor.logger.info('caps', **{'k' * 100: 'v', 'k' * 64 + 'other': 'w',
                                        'plain': 'x' * 1000, 'items': list(range(1000))})
        attributes = self.flushed_logs()[0]['attributes']
        self.assertEqual(attributes['k' * 64], {'value': 'v', 'type': 'string'})
        self.assertTrue(all(len(key) <= 64 for key in attributes))
        self.assertEqual(len(attributes['plain']['value']), 400)
        self.assertEqual(len(attributes['items']['value']), 400)

    def test_template_and_exception_text_keep_8000_characters(self):
        template = '{n} ' + 't' * 9000
        try:
            raise ValueError('m' * 9000)
        except ValueError:
            cronitor.logger.exception(template, n='p' * 1000)
        record = self.flushed_logs()[0]
        self.assertEqual(len(record['body']), 8000)
        self.assertEqual(_attr(record, 'sentry.message.template')['value'], template[:8000])
        self.assertEqual(len(_attr(record, 'sentry.message.parameter.n')['value']), 400)
        self.assertEqual(len(_attr(record, 'exception.message')['value']), 8000)
        self.assertEqual(len(_attr(record, 'exception.stacktrace')['value']), 8000)

    def test_stdlib_configuration_calls_still_work(self):
        import logging
        stdlib = logging.getLogger('cronitor')
        level = stdlib.level
        try:
            cronitor.logger.setLevel(logging.WARNING)
            self.assertEqual(stdlib.level, logging.WARNING)
            self.assertEqual(cronitor.logger.level, logging.WARNING)
        finally:
            stdlib.setLevel(level)
        with self.assertRaises(AttributeError):
            cronitor.logger.no_such_method


class StdlibLoggerCompatibilityTests(CaptureTestCase):
    """Calls written for logging.getLogger('cronitor'), which cronitor.logger was before 5.0."""

    def test_percent_args_are_formatted(self):
        cronitor.logger.info('x %s', 1)
        cronitor.logger.info('user %s did %d things', 'bob', 3)
        first, second = self.flushed_logs()
        self.assertEqual(first['body'], 'x 1')
        self.assertEqual(second['body'], 'user bob did 3 things')
        self.assertEqual(_attr(second, 'sentry.message.template')['value'], 'user %s did %d things')
        self.assertEqual(_attr(second, 'sentry.message.parameter.0'), {'value': 'bob', 'type': 'string'})
        self.assertEqual(_attr(second, 'sentry.message.parameter.1'), {'value': 3, 'type': 'integer'})

    def test_mapping_arg_and_attributes(self):
        cronitor.logger.info('%(user)s logged in', {'user': 'bob'}, team='core')
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], 'bob logged in')
        self.assertEqual(_attr(record, 'sentry.message.parameter.user')['value'], 'bob')
        self.assertEqual(_attr(record, 'team')['value'], 'core')

    def test_bad_format_keeps_the_body_and_never_raises(self):
        class Unprintable(object):
            def __str__(self):
                raise RuntimeError('no str')

        cronitor.logger.info('two %s %s', 1)
        cronitor.logger.info('number %d', 'not a number')
        cronitor.logger.info('object %s', Unprintable())
        self.assertEqual([r['body'] for r in self.flushed_logs()],
                         ['two %s %s', 'number %d', 'object %s'])

    def test_warn_and_critical_aliases(self):
        cronitor.logger.warn('careful %s', 'now')
        cronitor.logger.critical('down')
        warn, critical = self.flushed_logs()
        self.assertEqual((warn['level'], warn['body']), ('warn', 'careful now'))
        self.assertEqual(critical['level'], 'fatal')

    def test_exception_adds_the_handled_exception(self):
        try:
            raise ValueError('bad input')
        except ValueError:
            cronitor.logger.exception('import %s failed', 'orders', batch=4)
        record = self.flushed_logs()[0]
        self.assertEqual(self.send.events(), [])
        self.assertEqual((record['level'], record['body']), ('error', 'import orders failed'))
        self.assertEqual(_attr(record, 'exception.type')['value'], 'ValueError')
        self.assertEqual(_attr(record, 'exception.message')['value'], 'bad input')
        stacktrace = _attr(record, 'exception.stacktrace')['value']
        self.assertTrue(stacktrace.startswith('Traceback (most recent call last):'))
        self.assertTrue(stacktrace.rstrip().endswith('ValueError: bad input'))
        self.assertEqual(_attr(record, 'batch')['value'], 4)

    def test_exception_outside_an_except_block_is_an_error_log(self):
        cronitor.logger.exception('nothing raised')
        record = self.flushed_logs()[0]
        self.assertEqual(record['level'], 'error')
        self.assertNotIn('exception.type', record['attributes'])

    def test_log_with_stdlib_levels_and_names(self):
        cronitor.logger.log(logging.WARNING, 'w %s', 1)
        cronitor.logger.log(logging.CRITICAL, 'c')
        cronitor.logger.log(5, 'below debug')
        cronitor.logger.log('ERROR', 'e')
        cronitor.logger.log('warning', 'w')
        cronitor.logger.log('critical', 'c')
        cronitor.logger.log('trace', 't')
        cronitor.logger.log('no such level', 'unknown')
        records = self.flushed_logs()
        self.assertEqual([r['level'] for r in records],
                         ['warn', 'fatal', 'trace', 'error', 'warn', 'fatal', 'trace', 'info'])
        self.assertEqual(records[0]['body'], 'w 1')

    def test_log_with_a_registered_custom_level(self):
        logging.addLevelName(45, 'CRONITOR_TEST_SEVERE')
        cronitor.logger.log('cronitor_test_severe', 'custom')
        self.assertEqual(self.flushed_logs()[0]['level'], 'error')

    def test_logs_are_batched_into_one_envelope(self):
        for i in range(3):
            cronitor.logger.info('line {n}', n=i)
        self.flushed_logs()
        self.assertEqual(len(self.send.calls), 1)
        self.assertEqual(self.send.items('log')[0][0]['item_count'], 3)


@cronitor.job('capture-job-test')
def _successful_job():
    return 'done'


@cronitor.job('capture-job-test')
def _failing_job():
    raise ValueError('job exploded')


@cronitor.job('capture-job-test', env='staging')
def _job_that_reports():
    cronitor.capture_message('inside the job')
    cronitor.logger.info('log inside the job')
    try:
        raise KeyError('handled inside')
    except KeyError as e:
        cronitor.capture_exception(e)
    cronitor.capture_message('other monitor', monitor='someone-else')
    return 'ok'


class JobTests(CaptureTestCase):

    def setUp(self):
        super().setUp()
        patcher = patch('cronitor.Monitor.ping')
        self.ping = patcher.start()
        self.addCleanup(patcher.stop)

    def _ping_calls(self, state):
        return [c for c in self.ping.call_args_list if c.kwargs.get('state') == state]

    def test_success_sends_no_event(self):
        self.assertEqual(_successful_job(), 'done')
        self.assertEqual(len(self._ping_calls('complete')), 1)
        self.assertEqual(self.flushed_events(), [])

    def test_ping_failures_never_reach_the_job(self):
        # A telemetry outage must not stop the job: pings are best effort.
        self.ping.side_effect = requests.ConnectionError('telemetry host down')
        self.assertEqual(_successful_job(), 'done')
        self.assertEqual(len(self._ping_calls('run')), 1)
        self.assertEqual(len(self._ping_calls('complete')), 1)

    def test_ping_failure_still_captures_the_exception(self):
        self.ping.side_effect = requests.ConnectionError('telemetry host down')
        with self.assertRaises(ValueError):
            _failing_job()
        self.assertEqual(self.only_event()['exception']['values'][-1]['type'], 'ValueError')

    def test_failure_sends_fail_ping_then_unhandled_event_with_same_series(self):
        order = []
        self.ping.side_effect = lambda **params: order.append('ping:' + params['state'])
        real_submit = ingest.submit_event

        def submit(event, api_key=None):
            order.append('event')
            return real_submit(event, api_key=api_key)

        with patch('cronitor.ingest.submit_event', side_effect=submit):
            with self.assertRaises(ValueError):
                _failing_job()

        self.assertEqual(order, ['ping:run', 'ping:fail', 'event'])
        fail = self._ping_calls('fail')[0]
        series = fail.kwargs['series']
        self.assertEqual(self._ping_calls('run')[0].kwargs['series'], series)

        event = self.only_event()
        self.assertEqual(event['level'], 'error')
        self.assertEqual(event['tags'], {'cronitor.monitor': 'capture-job-test', 'cronitor.series': str(series)})
        values = event['exception']['values']
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]['type'], 'ValueError')
        self.assertEqual(values[0]['value'], 'job exploded')
        self.assertEqual(values[0]['mechanism'], {'type': 'cronitor.job', 'handled': False})
        self.assertEqual(values[0]['stacktrace']['frames'][-1]['function'], '_failing_job')

    def test_capture_exceptions_false_sends_no_event(self):
        cronitor.capture_exceptions = False
        with self.assertRaises(ValueError):
            _failing_job()
        self.assertEqual(len(self._ping_calls('fail')), 1)
        self.assertEqual(self.flushed_events(), [])

    def test_captures_inside_a_job_bind_to_the_run(self):
        cronitor.environment = 'production'
        self.assertEqual(_job_that_reports(), 'ok')
        series = str(self._ping_calls('run')[0].kwargs['series'])
        bound = {'cronitor.monitor': 'capture-job-test', 'cronitor.series': series}

        events = self.flushed_events()
        self.assertEqual(len(events), 3)
        message, handled, other = events
        self.assertEqual(message['tags'], bound)
        self.assertEqual(message['environment'], 'staging')
        self.assertEqual(handled['tags'], bound)
        self.assertEqual(handled['exception']['values'][0]['mechanism'], {'type': 'generic', 'handled': True})
        # an explicit other monitor is not bound to this run or its environment
        self.assertEqual(other['tags'], {'cronitor.monitor': 'someone-else'})
        self.assertEqual(other['environment'], 'production')

        record = self.send.log_records()[0]
        self.assertEqual(_attr(record, 'cronitor.monitor')['value'], 'capture-job-test')
        self.assertEqual(_attr(record, 'cronitor.series')['value'], series)
        self.assertEqual(_attr(record, 'sentry.environment')['value'], 'staging')

    def test_binding_ends_with_the_job(self):
        _successful_job()
        with self.assertRaises(ValueError):
            _failing_job()
        self.assertIsNone(cronitor.capture.current_job())
        cronitor.capture_message('after the job')
        self.assertEqual(self.flushed_events()[-1]['tags'], {})


class LogHandlerTests(CaptureTestCase):

    def setUp(self):
        super().setUp()
        self.log = logging.getLogger('cronitor.tests.handler')
        self.log.propagate = False
        self.log.setLevel(1)
        self.handler = cronitor.LogHandler(level=logging.NOTSET)
        self.log.addHandler(self.handler)
        self.addCleanup(self.log.removeHandler, self.handler)

    def test_level_mapping(self):
        self.log.log(5, 'below debug')
        self.log.debug('debug line')
        self.log.info('info line')
        self.log.warning('warning line')
        self.log.error('error line')
        self.log.critical('critical line')
        records = self.flushed_logs()
        self.assertEqual([r['level'] for r in records], ['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
        self.assertEqual([_attr(r, 'sentry.severity_number')['value'] for r in records], [1, 5, 9, 13, 17, 21])
        self.assertEqual(len(self.send.calls), 1)

    def test_record_attributes(self):
        before = time.time()
        self.log.info('user %s did %d things', 'bob', 3); line = sys._getframe().f_lineno
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], 'user bob did 3 things')
        self.assertGreaterEqual(record['timestamp'], before)
        self.assertEqual(_attr(record, 'logger.name'), {'value': 'cronitor.tests.handler', 'type': 'string'})
        self.assertEqual(_attr(record, 'code.file.path')['value'], __file__)
        self.assertEqual(_attr(record, 'code.line.number'), {'value': line, 'type': 'integer'})
        self.assertEqual(_attr(record, 'code.function.name')['value'], 'test_record_attributes')
        self.assertEqual(_attr(record, 'sentry.message.template')['value'], 'user %s did %d things')
        self.assertEqual(_attr(record, 'sentry.message.parameter.0'), {'value': 'bob', 'type': 'string'})
        self.assertEqual(_attr(record, 'sentry.message.parameter.1'), {'value': 3, 'type': 'integer'})
        self.assertEqual(_attr(record, 'sentry.sdk.name')['value'], 'cronitor-python')
        self.assertEqual(_attr(record, 'server.address')['value'], socket.gethostname())

    def test_mapping_args(self):
        self.log.info('%(user)s logged in', {'user': 'bob'})
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], 'bob logged in')
        self.assertEqual(_attr(record, 'sentry.message.parameter.user')['value'], 'bob')

    def test_no_args_records_no_template(self):
        self.log.info('100% plain')
        record = self.flushed_logs()[0]
        self.assertEqual(record['body'], '100% plain')
        self.assertNotIn('sentry.message.template', record['attributes'])

    def test_exc_info_adds_stacktrace_and_sends_no_event(self):
        try:
            raise ValueError('bad input')
        except ValueError:
            self.log.exception('import failed')
        records = self.flushed_logs()
        self.assertEqual(self.send.events(), [])
        record = records[0]
        self.assertEqual(record['level'], 'error')
        self.assertEqual(record['body'], 'import failed')
        stacktrace = _attr(record, 'exception.stacktrace')['value']
        self.assertTrue(stacktrace.startswith('Traceback (most recent call last):'))
        self.assertIn("raise ValueError('bad input')", stacktrace)
        self.assertTrue(stacktrace.rstrip().endswith('ValueError: bad input'))
        self.assertEqual(_attr(record, 'exception.type')['value'], 'ValueError')
        self.assertEqual(_attr(record, 'exception.message')['value'], 'bad input')

    def test_long_stacktrace_keeps_the_end(self):
        try:
            raise ValueError('x' * 9000 + ' the end')
        except ValueError:
            self.log.exception('failed')
        stacktrace = _attr(self.flushed_logs()[0], 'exception.stacktrace')['value']
        self.assertEqual(len(stacktrace), 8000)
        self.assertTrue(stacktrace.rstrip().endswith('the end'))

    def test_handler_level(self):
        self.handler.setLevel(logging.WARNING)
        self.log.info('dropped')
        self.log.warning('kept')
        self.assertEqual([r['body'] for r in self.flushed_logs()], ['kept'])

    def test_handler_level_argument(self):
        self.assertEqual(cronitor.LogHandler(logging.ERROR).level, logging.ERROR)
        self.assertEqual(cronitor.LogHandler(level=logging.DEBUG).level, logging.DEBUG)

    def test_default_level_is_info(self):
        # a root logger at DEBUG would otherwise ship every library's debug lines
        self.log.removeHandler(self.handler)
        handler = cronitor.LogHandler()
        self.assertEqual(handler.level, logging.INFO)
        self.log.addHandler(handler)
        self.addCleanup(self.log.removeHandler, handler)
        self.log.debug('dropped')
        self.log.info('kept')
        self.assertEqual([r['body'] for r in self.flushed_logs()], ['kept'])

    def test_long_parameters_are_capped(self):
        self.log.info('%s', 'p' * 1000)
        record = self.flushed_logs()[0]
        self.assertEqual(len(record['body']), 1000)
        self.assertEqual(len(_attr(record, 'sentry.message.parameter.0')['value']), 400)

    def test_records_inside_a_job_are_bound(self):
        @cronitor.job('handler-job')
        def job():
            self.log.info('working')

        with patch('cronitor.Monitor.ping') as ping:
            job()
        series = str(ping.call_args_list[0].kwargs['series'])
        record = self.flushed_logs()[0]
        self.assertEqual(_attr(record, 'cronitor.monitor')['value'], 'handler-job')
        self.assertEqual(_attr(record, 'cronitor.series')['value'], series)

    def test_ignores_the_transports_own_records(self):
        root = logging.getLogger()
        root.addHandler(self.handler)
        self.addCleanup(root.removeHandler, self.handler)
        logging.getLogger('cronitor.ingest').warning('send failed')
        ingest._worker_state.active = True
        try:
            logging.getLogger('urllib3.connectionpool').warning('retrying')
        finally:
            ingest._worker_state.active = False
        self.log.info('kept')
        self.assertEqual([r['body'] for r in self.flushed_logs()], ['kept'])


class ServiceSettingTests(CaptureTestCase):
    """cronitor.service binds every event and log record to a service monitor unless a call says otherwise."""

    def setUp(self):
        super().setUp()
        cronitor.service = None

    def tearDown(self):
        cronitor.service = None
        super().tearDown()

    def test_default_is_unset(self):
        self.assertIsNone(cronitor.service)
        cronitor.capture_message('hi')
        self.assertNotIn('cronitor.service', self.only_event()['tags'])

    def test_global_service_tags_events(self):
        cronitor.service = 'billing-api'
        cronitor.capture_message('hi', monitor='nightly-backup')
        self.assertEqual(self.only_event()['tags'],
                         {'cronitor.monitor': 'nightly-backup', 'cronitor.service': 'billing-api'})

    def test_explicit_tag_overrides_global_service(self):
        cronitor.service = 'billing-api'
        cronitor.capture_message('hi', tags={'cronitor.service': 'other-service'})
        self.assertEqual(self.only_event()['tags'], {'cronitor.service': 'other-service'})

    def test_global_service_on_log_records(self):
        cronitor.service = 'billing-api'
        cronitor.logger.info('hello')
        record = self.flushed_logs()[0]
        self.assertEqual(_attr(record, 'cronitor.service'), {'value': 'billing-api', 'type': 'string'})

    def test_log_attribute_overrides_global_service(self):
        cronitor.service = 'billing-api'
        cronitor.logger.info('hello', **{'cronitor.service': 'other-service'})
        record = self.flushed_logs()[0]
        self.assertEqual(_attr(record, 'cronitor.service')['value'], 'other-service')
