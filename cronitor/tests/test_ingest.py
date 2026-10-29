import gzip
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import cronitor
from cronitor import ingest
from cronitor.tests.envelope_parser import FakeResponse, RecordingSend, parse_envelope

FAKE_API_KEY = 'ingest-api-key'
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RFC3339_UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$')


def _event(event_id='a' * 32, **fields):
    event = {'event_id': event_id, 'level': 'error', 'platform': 'python'}
    event.update(fields)
    return event


def _record(body, level='info'):
    return {'timestamp': 1761768000.5, 'level': level, 'body': body, 'attributes': {}}


class EnvelopeSerializationTests(unittest.TestCase):

    def test_serialize_envelope_layout(self):
        raw = ingest.serialize_envelope({'event_id': 'b' * 32}, [({'type': 'event'}, b'{"x":1}')])
        self.assertEqual(raw, b'{"event_id":"' + b'b' * 32 + b'"}\n{"type":"event","length":7}\n{"x":1}\n')

    def test_length_counts_bytes_not_characters(self):
        payload = json.dumps({'body': 'caf\u00e9 \u2603'}, ensure_ascii=False).encode('utf-8')
        raw = ingest.serialize_envelope({}, [({'type': 'event'}, payload)])
        _, items = parse_envelope(raw, compressed=False)
        self.assertEqual(items[0][0]['length'], len(payload))
        self.assertEqual(items[0][1]['body'], 'caf\u00e9 \u2603')

    def test_event_envelope(self):
        payload = ingest.json_bytes(_event())
        header, items = parse_envelope(ingest.event_envelope(payload, 'a' * 32), compressed=False)
        self.assertEqual(header['event_id'], 'a' * 32)
        self.assertRegex(header['sent_at'], RFC3339_UTC)
        self.assertEqual(header['sdk'], {'name': 'cronitor-python', 'version': ingest.SDK_VERSION})
        self.assertEqual(len(items), 1)
        item_header, event = items[0]
        self.assertEqual(item_header, {'type': 'event', 'content_type': 'application/json', 'length': len(payload)})
        self.assertEqual(event['event_id'], 'a' * 32)

    def test_log_envelope(self):
        records = [_record('one'), _record('two', 'warn')]
        header, items = parse_envelope(ingest.log_envelope(records), compressed=False)
        self.assertNotIn('event_id', header)
        self.assertRegex(header['sent_at'], RFC3339_UTC)
        self.assertEqual(header['sdk']['name'], 'cronitor-python')
        item_header, payload = items[0]
        self.assertEqual(item_header['type'], 'log')
        self.assertEqual(item_header['item_count'], 2)
        self.assertEqual(item_header['content_type'], 'application/vnd.sentry.items.log+json')
        self.assertIn('length', item_header)
        self.assertEqual([r['body'] for r in payload['items']], ['one', 'two'])

    def test_format_timestamp(self):
        from datetime import datetime, timezone
        stamp = datetime(2026, 10, 29, 20, 0, 0, 123456, tzinfo=timezone.utc)
        self.assertEqual(ingest.format_timestamp(stamp), '2026-10-29T20:00:00.123456Z')


class UrlTests(unittest.TestCase):

    def setUp(self):
        self._saved = cronitor.ingest_url

    def tearDown(self):
        cronitor.ingest_url = self._saved

    def test_default_urls_unchanged(self):
        cronitor.ingest_url = ingest.DEFAULT_INGEST_URL
        self.assertEqual(ingest.envelope_url(), 'https://cronitor.link/api/envelope')
        monitor = cronitor.Monitor('my-job', api_key='abc')
        self.assertEqual(monitor._ping_api_url(), 'https://cronitor.link/p/abc/my-job')

    def test_ingest_url_setting_moves_pings_and_envelopes(self):
        cronitor.ingest_url = 'http://localhost:9100/'
        self.assertEqual(ingest.envelope_url(), 'http://localhost:9100/api/envelope')
        monitor = cronitor.Monitor('my-job', api_key='abc')
        self.assertEqual(monitor._ping_api_url(), 'http://localhost:9100/p/abc/my-job')

    def test_unset_ingest_url_falls_back_to_default(self):
        cronitor.ingest_url = None
        self.assertEqual(ingest.envelope_url(), 'https://cronitor.link/api/envelope')

    def test_env_var_sets_ingest_url(self):
        script = (
            'import cronitor\n'
            'from cronitor import ingest\n'
            'print(cronitor.ingest_url)\n'
            'print(ingest.envelope_url())\n'
            'print(cronitor.Monitor("my-job", api_key="abc")._ping_api_url())\n'
        )
        env = dict(os.environ, CRONITOR_INGEST_URL='http://localhost:9100')
        env.pop('CRONITOR_CONFIG', None)
        out = subprocess.run([sys.executable, '-c', script], cwd=REPO_ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.decode().split(), [
            'http://localhost:9100',
            'http://localhost:9100/api/envelope',
            'http://localhost:9100/p/abc/my-job',
        ])


class TransportTests(unittest.TestCase):

    def setUp(self):
        self._saved_key = cronitor.api_key
        self._saved_url = cronitor.ingest_url
        cronitor.api_key = FAKE_API_KEY
        cronitor.ingest_url = ingest.DEFAULT_INGEST_URL
        self.sleeps = []
        self.send = RecordingSend()
        self.transport = ingest.Transport(send=self.send, sleep=self.sleeps.append)

    def tearDown(self):
        self.transport.flush(1.0)
        cronitor.api_key = self._saved_key
        cronitor.ingest_url = self._saved_url

    def test_event_is_sent_gzipped_with_headers(self):
        self.assertTrue(self.transport.submit_event(_event()))
        self.assertTrue(self.transport.flush(2.0))
        self.assertEqual(len(self.send.calls), 1)
        call = self.send.calls[0]
        self.assertEqual(call.url, 'https://cronitor.link/api/envelope')
        self.assertEqual(call.timeout, 5)
        self.assertEqual(call.headers, {
            'Content-Type': 'application/x-sentry-envelope',
            'Content-Encoding': 'gzip',
            'User-Agent': 'cronitor-python',
            'X-Sentry-Auth': 'Sentry sentry_key=%s, sentry_version=7, sentry_client=cronitor-python/%s'
                             % (FAKE_API_KEY, ingest.SDK_VERSION),
        })
        self.assertEqual(call.data[:2], b'\x1f\x8b')
        header, items = parse_envelope(call.data)
        self.assertEqual(header['event_id'], 'a' * 32)
        self.assertEqual(items[0][0]['type'], 'event')

    def test_one_envelope_per_event(self):
        self.transport.submit_event(_event('1' * 32))
        self.transport.submit_event(_event('2' * 32))
        self.transport.flush(2.0)
        self.assertEqual([h['event_id'] for h, _ in self.send.envelopes()], ['1' * 32, '2' * 32])
        for _, items in self.send.envelopes():
            self.assertEqual(len(items), 1)

    def test_api_key_and_url_are_taken_at_submit_time(self):
        self.transport.submit_event(_event(), api_key='other-key')
        cronitor.ingest_url = 'http://localhost:9100'
        self.transport.submit_event(_event())
        self.transport.flush(2.0)
        self.assertIn('sentry_key=other-key,', self.send.calls[0].headers['X-Sentry-Auth'])
        self.assertEqual(self.send.calls[0].url, 'https://cronitor.link/api/envelope')
        self.assertEqual(self.send.calls[1].url, 'http://localhost:9100/api/envelope')

    def test_no_api_key_sends_nothing(self):
        cronitor.api_key = None
        with self.assertLogs('cronitor.ingest', 'ERROR'):
            self.assertFalse(self.transport.submit_event(_event()))
        self.transport.flush(1.0)
        self.assertEqual(self.send.calls, [])

    def test_logs_batch_until_flush(self):
        for i in range(3):
            self.transport.submit_log(_record('line %d' % i))
        self.assertTrue(self.transport.flush(2.0))
        self.assertEqual(len(self.send.calls), 1)
        _, items = self.send.envelopes()[0]
        self.assertEqual(items[0][0]['item_count'], 3)
        self.assertEqual([r['body'] for r in items[0][1]['items']], ['line 0', 'line 1', 'line 2'])

    def test_logs_batch_by_count(self):
        for i in range(250):
            self.transport.submit_log(_record('line %d' % i))
        # two full batches go out without a flush
        self.assertTrue(self.send.wait_for(2))
        self.transport.flush(2.0)
        counts = [items[0][0]['item_count'] for _, items in self.send.envelopes()]
        self.assertEqual(counts, [100, 100, 50])
        self.assertEqual(len(self.send.log_records()), 250)

    def test_logs_batch_by_time(self):
        transport = ingest.Transport(send=self.send, batch_interval=0.1)
        transport.submit_log(_record('late line'))
        self.assertTrue(self.send.wait_for(1, timeout=2.0))
        self.assertEqual([r['body'] for r in self.send.log_records()], ['late line'])

    def test_events_do_not_wait_for_log_batch(self):
        self.transport.submit_log(_record('buffered'))
        self.transport.submit_event(_event())
        self.assertTrue(self.send.wait_for(1))
        self.assertEqual(self.send.items()[0][0]['type'], 'event')
        self.transport.flush(2.0)
        self.assertEqual([h['type'] for h, _ in self.send.items()], ['event', 'log'])

    def test_send_exception_is_swallowed_and_logged(self):
        self.send.raises = ConnectionError('network down')
        with self.assertLogs('cronitor.ingest', 'WARNING') as logs:
            self.assertTrue(self.transport.submit_event(_event()))
            self.assertTrue(self.transport.flush(2.0))
        self.assertIn('network down', '\n'.join(logs.output))
        # the worker survives and keeps sending
        self.send.raises = None
        self.transport.submit_event(_event('c' * 32))
        self.transport.flush(2.0)
        self.assertEqual(len(self.send.calls), 2)

    def test_error_status_is_logged(self):
        self.send.responses = [FakeResponse(403)]
        with self.assertLogs('cronitor.ingest', 'WARNING') as logs:
            self.transport.submit_event(_event())
            self.transport.flush(2.0)
        self.assertIn('403', '\n'.join(logs.output))

    def test_429_sleeps_retry_after_before_next_send(self):
        self.send.responses = [FakeResponse(429, {'Retry-After': '7'})]
        with self.assertLogs('cronitor.ingest', 'WARNING'):
            self.transport.submit_event(_event('1' * 32))
            self.transport.flush(2.0)
        self.assertEqual(self.sleeps, [])
        self.transport.submit_event(_event('2' * 32))
        self.transport.flush(2.0)
        self.assertEqual(len(self.sleeps), 1)
        self.assertAlmostEqual(self.sleeps[0], 7, delta=1)
        self.assertEqual(len(self.send.calls), 2)

    def test_429_retry_after_is_capped_at_60_seconds(self):
        self.send.responses = [FakeResponse(429, {'Retry-After': '3600'})]
        with self.assertLogs('cronitor.ingest', 'WARNING'):
            self.transport.submit_event(_event('1' * 32))
            self.transport.flush(2.0)
        self.transport.submit_log(_record('after the limit'))
        self.transport.flush(2.0)
        self.assertEqual(len(self.sleeps), 1)
        self.assertLessEqual(self.sleeps[0], 60)
        self.assertGreater(self.sleeps[0], 58)

    def test_429_without_retry_after_waits_60_seconds(self):
        self.send.responses = [FakeResponse(429)]
        with self.assertLogs('cronitor.ingest', 'WARNING'):
            self.transport.submit_event(_event('1' * 32))
            self.transport.flush(2.0)
        self.transport.submit_event(_event('2' * 32))
        self.transport.flush(2.0)
        self.assertGreater(self.sleeps[0], 58)

    def test_full_queue_drops_and_counts(self):
        release = threading.Event()
        started = threading.Event()

        def blocking_send(url, data, headers, timeout):
            started.set()
            release.wait(5)
            return FakeResponse(200)

        transport = ingest.Transport(send=blocking_send, maxsize=2)
        transport.submit_event(_event('0' * 32))
        self.assertTrue(started.wait(2))
        results = [transport.submit_event(_event(str(i) * 32)) for i in range(1, 6)]
        self.assertEqual(results, [True, True, False, False, False])
        self.assertEqual(transport.dropped, 3)
        release.set()
        self.assertTrue(transport.flush(2.0))

    def test_flush_without_activity_returns_immediately(self):
        transport = ingest.Transport(send=self.send)
        self.assertTrue(transport.flush(0.1))
        self.assertEqual(self.send.calls, [])

    def test_new_worker_after_fork(self):
        self.transport.submit_event(_event('1' * 32))
        self.transport.flush(2.0)
        first_thread = self.transport._thread
        # simulate running in a forked child: the parent's thread does not exist there
        with patch('os.getpid', return_value=os.getpid() + 100000):
            self.transport.submit_event(_event('2' * 32))
            self.assertTrue(self.transport.flush(2.0))
            self.assertIsNot(self.transport._thread, first_thread)
        self.assertEqual(len(self.send.calls), 2)


class ModuleTransportTests(unittest.TestCase):

    def test_set_transport_returns_previous(self):
        replacement = ingest.Transport(send=RecordingSend())
        previous = ingest.set_transport(replacement)
        try:
            self.assertIs(ingest.get_transport(), replacement)
        finally:
            ingest.set_transport(previous)
        self.assertIs(ingest.get_transport(), previous)

    def test_flush_at_exit(self):
        script = (
            'import sys, gzip\n'
            'import cronitor\n'
            'from cronitor import ingest\n'
            'class R(object):\n'
            '    status_code = 200\n'
            '    headers = {}\n'
            'def send(url, data, headers, timeout):\n'
            '    sys.stdout.write("SENT %d\\n" % gzip.decompress(data).count(b"\\n"))\n'
            '    sys.stdout.flush()\n'
            '    return R()\n'
            'ingest.set_transport(ingest.Transport(send=send))\n'
            'cronitor.api_key = "k"\n'
            'ingest.submit_log({"timestamp": 1.0, "level": "info", "body": "bye", "attributes": {}})\n'
        )
        env = dict(os.environ)
        env.pop('CRONITOR_CONFIG', None)
        out = subprocess.run([sys.executable, '-c', script], cwd=REPO_ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.decode().strip(), 'SENT 3')


class LocalCollectorTests(unittest.TestCase):
    """The default requests-based send path against a loopback HTTP server."""

    def setUp(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        received = self.received = []
        statuses = self.statuses = []

        class Handler(BaseHTTPRequestHandler):
            def _record(self):
                length = int(self.headers.get('Content-Length') or 0)
                received.append((self.command, self.path, dict(self.headers), self.rfile.read(length)))
                status, headers = statuses.pop(0) if statuses else (200, {})
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

            do_GET = do_POST = _record

            def log_message(self, *args):
                pass

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._saved = (cronitor.api_key, cronitor.ingest_url)
        cronitor.api_key = FAKE_API_KEY
        cronitor.ingest_url = 'http://127.0.0.1:%d' % self.server.server_port
        no_proxy = '127.0.0.1,' + os.environ.get('NO_PROXY', os.environ.get('no_proxy', ''))
        env = patch.dict(os.environ, {'NO_PROXY': no_proxy, 'no_proxy': no_proxy})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        cronitor.api_key, cronitor.ingest_url = self._saved

    def test_envelopes_and_pings_reach_the_ingest_url(self):
        sleeps = []
        transport = ingest.Transport(sleep=sleeps.append)
        self.statuses.extend([(200, {}), (429, {'Retry-After': '3'}), (200, {})])
        transport.submit_event(_event('1' * 32))
        transport.submit_event(_event('2' * 32))
        with self.assertLogs('cronitor.ingest', 'WARNING'):
            self.assertTrue(transport.flush(5.0))
        transport.submit_log(_record('after 429'))
        self.assertTrue(transport.flush(5.0))

        self.assertEqual(len(self.received), 3)
        method, path, headers, body = self.received[0]
        self.assertEqual((method, path), ('POST', '/api/envelope'))
        self.assertEqual(headers['Content-Type'], 'application/x-sentry-envelope')
        self.assertEqual(headers['Content-Encoding'], 'gzip')
        self.assertEqual(headers['User-Agent'], 'cronitor-python')
        self.assertTrue(headers['X-Sentry-Auth'].startswith('Sentry sentry_key=%s, sentry_version=7,' % FAKE_API_KEY))
        header, items = parse_envelope(body)
        self.assertEqual(header['event_id'], '1' * 32)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 3, delta=1)
        self.assertEqual(parse_envelope(self.received[2][3])[1][0][1]['items'][0]['body'], 'after 429')

        cronitor.Monitor('local-job').ping(state='run')
        method, path, _, _ = self.received[3]
        self.assertEqual(method, 'GET')
        self.assertTrue(path.startswith('/p/%s/local-job?' % FAKE_API_KEY), path)
