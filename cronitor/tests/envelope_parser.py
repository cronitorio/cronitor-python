"""Test helpers: a small reference parser for envelope bytes and a fake send function.

The parser is intentionally independent of cronitor.ingest so tests check the
bytes on the wire, not the code that produced them.
"""
import gzip
import json
import threading
import time


def _reject_constant(name):
    raise ValueError('not valid JSON: %s' % name)


def parse_envelope(body, compressed=True):
    """Parse envelope bytes into (header, [(item_header, payload), ...]).

    Layout: one JSON header line, then for each item a JSON item header line,
    exactly `length` payload bytes, and a newline.
    """
    raw = gzip.decompress(body) if compressed else body
    header_line, sep, rest = raw.partition(b'\n')
    if not sep:
        raise AssertionError('envelope header is not newline terminated')
    header = json.loads(header_line.decode('utf-8'))
    items = []
    while rest:
        item_header_line, sep, rest = rest.partition(b'\n')
        if not sep:
            raise AssertionError('item header is not newline terminated')
        item_header = json.loads(item_header_line.decode('utf-8'))
        if 'length' not in item_header:
            raise AssertionError('item header has no length: %r' % item_header)
        length = item_header['length']
        if len(rest) < length:
            raise AssertionError('payload shorter than length %d' % length)
        payload, rest = rest[:length], rest[length:]
        if rest[:1] != b'\n':
            raise AssertionError('payload is not followed by a newline')
        rest = rest[1:]
        items.append((item_header, json.loads(payload.decode('utf-8'), parse_constant=_reject_constant)))
    return header, items


class FakeResponse(object):
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class SentRequest(object):
    def __init__(self, url, data, headers, timeout):
        self.url = url
        self.data = data
        self.headers = headers
        self.timeout = timeout

    @property
    def envelope(self):
        return parse_envelope(self.data)


class RecordingSend(object):
    """Injectable send(url, data, headers, timeout) that records every call."""

    def __init__(self, responses=None, raises=None):
        self.calls = []
        self.responses = list(responses or [])
        self.raises = raises
        self._lock = threading.Lock()

    def __call__(self, url, data, headers, timeout):
        with self._lock:
            self.calls.append(SentRequest(url, data, headers, timeout))
            if self.raises is not None:
                raise self.raises
            if self.responses:
                return self.responses.pop(0)
            return FakeResponse(200)

    def envelopes(self):
        return [c.envelope for c in self.calls]

    def items(self, item_type=None):
        out = []
        for _, items in self.envelopes():
            for item_header, payload in items:
                if item_type is None or item_header['type'] == item_type:
                    out.append((item_header, payload))
        return out

    def events(self):
        return [payload for _, payload in self.items('event')]

    def log_records(self):
        records = []
        for _, payload in self.items('log'):
            records.extend(payload['items'])
        return records

    def wait_for(self, count, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.calls) >= count:
                return True
            time.sleep(0.01)
        return len(self.calls) >= count
