"""Envelope encoding and background transport for exception events and logs.

Payloads use the Sentry envelope format and are sent to
``{cronitor.ingest_url}/api/envelope``. Sending happens on one daemon thread
with a bounded queue, so callers are never blocked by the network and never
see a transport error.
"""
import atexit
import gzip
import json
import logging
import math
import os
import queue
import threading
import time
from datetime import datetime, timezone

import cronitor
from ._version import __version__

logger = logging.getLogger(__name__)

DEFAULT_INGEST_URL = 'https://cronitor.link'
SDK_NAME = 'cronitor-python'
SDK_VERSION = __version__

MAX_QUEUE_SIZE = 1000
LOG_BATCH_SIZE = 100
LOG_BATCH_INTERVAL = 5.0
SEND_TIMEOUT = 5
SEND_RETRIES = 1
MAX_RETRY_AFTER = 60.0
ATEXIT_FLUSH_TIMEOUT = 2.0
# the server drops event items over 1 MB; oversized events are trimmed to this
MAX_EVENT_BYTES = 900 * 1024
TRIMMED_FRAMES = 20

EVENT_CONTENT_TYPE = 'application/json'
LOG_CONTENT_TYPE = 'application/vnd.sentry.items.log+json'

_worker_state = threading.local()
_start_lock = threading.Lock()


def _reset_after_fork():
    # a lock held by another thread at fork time stays locked forever in the child
    global _start_lock
    _start_lock = threading.Lock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_after_fork)


def base_url():
    """The scheme and host that pings and envelopes are sent to, without a trailing slash."""
    return (cronitor.ingest_url or DEFAULT_INGEST_URL).rstrip('/')


def envelope_url():
    return '{}/api/envelope'.format(base_url())


def sdk_info():
    return {'name': SDK_NAME, 'version': SDK_VERSION}


def auth_header(api_key):
    return 'Sentry sentry_key={}, sentry_version=7, sentry_client={}/{}'.format(api_key, SDK_NAME, SDK_VERSION)


def request_headers(api_key):
    return {
        'Content-Type': 'application/x-sentry-envelope',
        'Content-Encoding': 'gzip',
        'User-Agent': 'cronitor-python',
        'X-Sentry-Auth': auth_header(api_key),
    }


def format_timestamp(value=None):
    """RFC 3339 in UTC with microseconds and a Z suffix."""
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _json_default(value):
    try:
        return repr(value)
    except Exception:
        return '<unrepresentable %s>' % type(value).__name__


def _json_safe(value, depth=0):
    """Copy of value with NaN/Infinity as strings and nesting (and so cycles) cut at 10 levels."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, (dict, list, tuple)) and depth >= 10:
        return _json_default(value)
    if isinstance(value, dict):
        return {k: _json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, depth + 1) for v in value]
    return value


def _dumps(obj, allow_nan):
    return json.dumps(obj, default=_json_default, ensure_ascii=False, separators=(',', ':'),
                      skipkeys=True, allow_nan=allow_nan)


def json_bytes(obj):
    """Strict JSON (no NaN or Infinity) as UTF-8. Values json cannot encode become their repr."""
    try:
        text = _dumps(obj, allow_nan=False)
    except ValueError:
        # a non-finite float or a circular reference somewhere in user data
        text = _dumps(_json_safe(obj), allow_nan=False)
    # 'replace' turns lone surrogates (undecodable bytes in paths or messages) into '?'
    return text.encode('utf-8', 'replace')


def serialize_envelope(headers, items):
    """Build envelope bytes from a header dict and (item_header, payload_bytes) pairs.

    Every item header gets a ``length`` equal to the payload's byte length.
    """
    parts = [json_bytes(headers), b'\n']
    for item_headers, payload in items:
        item_headers = dict(item_headers, length=len(payload))
        parts.extend([json_bytes(item_headers), b'\n', payload, b'\n'])
    return b''.join(parts)


def event_bytes(event):
    """The event as JSON bytes, trimmed to at most MAX_EVENT_BYTES when possible.

    An oversized event loses, until it fits: every frame's source context, then
    ``extra``, then all but the last 20 frames of each exception.
    ``extra['_trimmed']`` says what was dropped. The caller's dict is not changed.
    """
    payload = json_bytes(event)
    if len(payload) <= MAX_EVENT_BYTES:
        return payload
    try:
        event = dict(event)
        dropped = []
        for note, trim in _EVENT_TRIMS:
            if not trim(event):
                continue
            dropped.append(note)
            extra = event.get('extra')
            extra = dict(extra) if isinstance(extra, dict) else {}
            extra['_trimmed'] = '%s: event over %d KB' % ('; '.join(dropped), MAX_EVENT_BYTES // 1024)
            event['extra'] = extra
            payload = json_bytes(event)
            if len(payload) <= MAX_EVENT_BYTES:
                break
    except Exception as e:
        logger.warning('Cronitor could not trim an oversized event: %s', e)
    return payload


def _own_frames(event):
    """Give event its own copies of the exception values and frames, and return the frame lists."""
    exception = event.get('exception') or {}
    values, frame_lists = [], []
    for value in exception.get('values') or []:
        stacktrace = value.get('stacktrace') or {}
        if stacktrace.get('frames'):
            frames = [dict(frame) for frame in stacktrace['frames']]
            value = dict(value, stacktrace=dict(stacktrace, frames=frames))
            frame_lists.append(frames)
        values.append(value)
    if values:
        event['exception'] = dict(exception, values=values)
    return frame_lists


def _drop_source_context(event):
    dropped = False
    for frames in _own_frames(event):
        for frame in frames:
            for key in ('pre_context', 'post_context'):
                if key in frame:
                    del frame[key]
                    dropped = True
    return dropped


def _drop_extra(event):
    extra = event.get('extra')
    if not isinstance(extra, dict) or all(key == '_trimmed' for key in extra):
        return False
    event['extra'] = {}
    return True


def _keep_last_frames(event):
    cut = False
    for frames in _own_frames(event):
        if len(frames) > TRIMMED_FRAMES:
            del frames[:-TRIMMED_FRAMES]
            cut = True
    return cut


_EVENT_TRIMS = (
    ('source context dropped', _drop_source_context),
    ('extra dropped', _drop_extra),
    ('frames cut to the last %d per exception' % TRIMMED_FRAMES, _keep_last_frames),
)


def event_envelope(payload, event_id, sent_at=None):
    headers = {'event_id': event_id, 'sent_at': format_timestamp(sent_at), 'sdk': sdk_info()}
    item = {'type': 'event', 'content_type': EVENT_CONTENT_TYPE}
    return serialize_envelope(headers, [(item, payload)])


def log_envelope(records, sent_at=None):
    headers = {'sent_at': format_timestamp(sent_at), 'sdk': sdk_info()}
    item = {'type': 'log', 'item_count': len(records), 'content_type': LOG_CONTENT_TYPE}
    return serialize_envelope(headers, [(item, json_bytes({'items': records}))])


def in_worker_thread():
    """True on the transport thread, so log handlers can ignore records the transport itself causes."""
    return getattr(_worker_state, 'active', False)


def _seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) else None


def _retry_after(response):
    """Seconds to stop sending after a 429, at most MAX_RETRY_AFTER.

    As in Sentry's SDKs, X-Sentry-Rate-Limits wins over Retry-After; the first
    field of its first entry is the retry-after in seconds. With neither, the maximum.
    """
    headers = getattr(response, 'headers', None) or {}
    delay = None
    limits = headers.get('X-Sentry-Rate-Limits')
    if limits:
        delay = _seconds(limits.split(',')[0].split(':')[0])
    if delay is None:
        delay = _seconds(headers.get('Retry-After'))
    if delay is None:
        delay = MAX_RETRY_AFTER
    return max(0.0, min(delay, MAX_RETRY_AFTER))


class Transport(object):
    """Sends envelopes from a single daemon thread.

    ``send(url, data, headers, timeout)`` performs the HTTP request and returns a
    response with ``status_code`` and ``headers``; it is injectable for tests.
    ``dropped`` counts the items lost to a full queue or to a rate limit.
    """

    def __init__(self, send=None, maxsize=MAX_QUEUE_SIZE,
                 batch_size=LOG_BATCH_SIZE, batch_interval=LOG_BATCH_INTERVAL):
        self._send = send or self._http_send
        self._maxsize = maxsize
        self._batch_size = batch_size
        self._batch_interval = batch_interval
        self._session = None
        self._queue = None
        self._thread = None
        self._pid = None
        self._rate_limited_until = 0.0
        self._reported_rate_limit = False
        self._reported_missing_key = False
        self.dropped = 0

    # caller side

    def submit_event(self, event, api_key=None):
        """Queue one event dict. Returns False when it was not queued."""
        api_key = self._api_key(api_key)
        if not api_key:
            return False
        return self._put(('event', envelope_url(), api_key, event['event_id'], event_bytes(event)))

    def submit_log(self, record, api_key=None):
        """Queue one log record dict. Returns False when it was not queued."""
        api_key = self._api_key(api_key)
        if not api_key:
            return False
        return self._put(('log', envelope_url(), api_key, record))

    def flush(self, timeout=2.0):
        """Wait up to ``timeout`` seconds for queued items, including buffered logs, to be sent."""
        if self._thread is None or self._pid != os.getpid() or not self._thread.is_alive():
            return True
        deadline = time.monotonic() + timeout
        done = threading.Event()
        try:
            self._queue.put(('flush', done), timeout=timeout)
        except queue.Full:
            return False
        return done.wait(max(0.0, deadline - time.monotonic()))

    def _api_key(self, api_key):
        api_key = api_key or cronitor.api_key
        if not api_key and not self._reported_missing_key:
            self._reported_missing_key = True
            logger.error('No API key detected. Set cronitor.api_key to send exceptions and logs.')
        return api_key

    def _put(self, item):
        try:
            self._ensure_worker()
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                logger.warning('Cronitor ingest queue is full, %d item(s) dropped so far.', self.dropped)
            return False
        except Exception as e:
            logger.warning('Cronitor could not queue an item: %s', e)
            return False

    def _ensure_worker(self):
        pid = os.getpid()
        if self._pid == pid and self._thread is not None and self._thread.is_alive():
            return
        with _start_lock:
            if self._pid == pid and self._thread is not None and self._thread.is_alive():
                return
            if self._pid != pid or self._queue is None:
                # first use, or a forked child: items queued by the parent are not ours to send
                self._queue = queue.Queue(maxsize=self._maxsize)
            if self._pid != pid:
                # nor is its keep-alive session: the sockets are shared with the parent, and a
                # connection pool lock held by a parent thread at fork time is never released
                self._session = None
                self._rate_limited_until = 0.0
            thread = threading.Thread(target=self._run, args=(self._queue,), name='cronitor-ingest')
            thread.daemon = True
            thread.start()
            self._thread = thread
            self._pid = pid
        _register_atexit()

    # worker side

    def _run(self, q):
        _worker_state.active = True
        buffers = {}
        deadline = None
        while True:
            timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                item = q.get(timeout=timeout)
            except queue.Empty:
                self._flush_logs(buffers)
                deadline = None
                continue
            try:
                kind = item[0]
                if kind == 'event':
                    _, url, api_key, event_id, payload = item
                    self._deliver(url, api_key, event_envelope(payload, event_id))
                elif kind == 'log':
                    _, url, api_key, record = item
                    batch = buffers.setdefault((url, api_key), [])
                    batch.append(record)
                    if deadline is None:
                        deadline = time.monotonic() + self._batch_interval
                    if len(batch) >= self._batch_size:
                        del buffers[(url, api_key)]
                        self._deliver(url, api_key, log_envelope(batch), len(batch))
                        if not buffers:
                            deadline = None
                elif kind == 'flush':
                    self._flush_logs(buffers)
                    deadline = None
                    item[1].set()
            except Exception as e:
                logger.warning('Cronitor could not send an envelope: %s', e)
            finally:
                q.task_done()

    def _flush_logs(self, buffers):
        while buffers:
            (url, api_key), batch = buffers.popitem()
            try:
                self._deliver(url, api_key, log_envelope(batch), len(batch))
            except Exception as e:
                logger.warning('Cronitor could not send logs: %s', e)

    def _deliver(self, url, api_key, body, count=1):
        """Send one envelope holding ``count`` items, or drop it while rate limited."""
        left = self._rate_limited_until - time.monotonic()
        if left > 0:
            # dropped rather than waited out, so the items queued behind it are not
            # delayed into the exit flush and lost there
            self.dropped += count
            if not self._reported_rate_limit:
                self._reported_rate_limit = True
                logger.warning('Cronitor is rate limited for %.0f more seconds; dropping envelopes until then.', left)
            return
        try:
            response = self._send(url, gzip.compress(body, 6), request_headers(api_key), SEND_TIMEOUT)
        except Exception as e:
            logger.warning('Cronitor could not send an envelope to %s: %s', url, e)
            return
        status = getattr(response, 'status_code', None)
        if status == 429:
            delay = _retry_after(response)
            self._rate_limited_until = time.monotonic() + delay
            self._reported_rate_limit = False
            logger.warning('Cronitor rate limited the envelope (HTTP 429); not sending for %.0f seconds.', delay)
        elif status is not None and status >= 400:
            logger.warning('Cronitor rejected an envelope with HTTP %s.', status)

    def _http_send(self, url, data, headers, timeout):
        if self._session is None:
            from .monitor import retry_session
            self._session = retry_session(retries=SEND_RETRIES)
        return self._session.post(url, data=data, headers=headers, timeout=timeout)


_transport = Transport()
_atexit_registered = False


def get_transport():
    return _transport


def set_transport(transport):
    """Replace the module transport (for tests or a custom ``send``). Returns the previous one."""
    global _transport
    previous, _transport = _transport, transport
    return previous


def submit_event(event, api_key=None):
    return _transport.submit_event(event, api_key=api_key)


def submit_log(record, api_key=None):
    return _transport.submit_log(record, api_key=api_key)


def flush(timeout=2.0):
    """Block up to ``timeout`` seconds while queued events and logs are sent."""
    try:
        return _transport.flush(timeout)
    except Exception as e:
        logger.warning('Cronitor flush failed: %s', e)
        return False


def _flush_at_exit():
    flush(ATEXIT_FLUSH_TIMEOUT)


def _register_atexit():
    global _atexit_registered
    if not _atexit_registered:
        _atexit_registered = True
        atexit.register(_flush_at_exit)
