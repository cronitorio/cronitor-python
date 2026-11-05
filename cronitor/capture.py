"""Exception, message and log capture.

Events and log records are bound to a monitor and a run with the reserved
names ``cronitor.monitor`` and ``cronitor.series`` (tags on events, attributes
on logs). Inside ``@cronitor.job`` both are filled in automatically.
"""
import contextvars
import linecache
import logging
import math
import os
import socket
import sys
import sysconfig
import time
import traceback
import uuid
from collections import namedtuple
from collections.abc import Mapping

import cronitor
from . import ingest

_log = logging.getLogger(__name__)

MONITOR_TAG = 'cronitor.monitor'
SERIES_TAG = 'cronitor.series'
SERVICE_TAG = 'cronitor.service'

MAX_VALUE_LENGTH = 4000
MAX_MESSAGE_LENGTH = 4000
MAX_LOG_BODY_LENGTH = 8000
MAX_TAGS = 50
MAX_TAG_KEY_LENGTH = 64
MAX_TAG_VALUE_LENGTH = 400
MAX_ATTRIBUTES = 50
MAX_ATTRIBUTE_KEY_LENGTH = 64
MAX_ATTRIBUTE_VALUE_LENGTH = 400
# log attributes holding long text, which the server keeps as long as a body
TEXT_ATTRIBUTES = frozenset(['exception.stacktrace', 'exception.message', 'sentry.message.template'])
MAX_TEXT_ATTRIBUTE_LENGTH = 8000
MAX_CHAINED_EXCEPTIONS = 10
MAX_FRAMES = 100
MAX_LINE_LENGTH = 1000
CONTEXT_LINES = 5

EVENT_LEVELS = {
    'fatal': 'fatal', 'critical': 'fatal', 'error': 'error', 'warning': 'warning',
    'warn': 'warning', 'info': 'info', 'debug': 'debug',
}
LOG_SEVERITY = {'trace': 1, 'debug': 5, 'info': 9, 'warn': 13, 'error': 17, 'fatal': 21}

JobContext = namedtuple('JobContext', ['monitor', 'series', 'env'])
_current_job = contextvars.ContextVar('cronitor_job', default=None)


def current_job():
    """The (monitor, series, env) of the enclosing ``@cronitor.job``, or None."""
    return _current_job.get()


def bind_job(monitor, series, env):
    """Bind captures in this context to a run. Returns a token for ``unbind_job``."""
    return _current_job.set(JobContext(monitor, series, env))


def unbind_job(token):
    _current_job.reset(token)


# public API

def capture_exception(exc=None, *, monitor=None, series=None, level='error', tags=None, extra=None):
    """Send an exception event. ``exc`` defaults to the exception being handled.

    Returns the event id, or None when nothing was sent.
    """
    return _capture_exception(exc, monitor=monitor, series=series, level=level, tags=tags, extra=extra)


def capture_message(message, level='info', *, monitor=None, series=None, tags=None, extra=None):
    """Send a message event. Returns the event id, or None when nothing was sent."""
    return _capture_message(message, level=level, monitor=monitor, series=series, tags=tags, extra=extra)


class Logger(object):
    """Structured logs shipped to Cronitor, mirroring ``sentry_sdk.logger``.

    ``cronitor.logger.info('processed {count} rows', count=5)`` formats the body
    with ``str.format`` and records the template and parameters as attributes.

    Before 5.0 ``cronitor.logger`` was ``logging.getLogger('cronitor')``, so calls
    written for it keep working: %-style arguments (``info('x %s', 1)``), ``warn``,
    ``critical``, ``exception`` and ``log(level, ...)``.
    """

    def trace(self, body, *args, **attributes):
        _capture_log('trace', body, attributes, args=args)

    def debug(self, body, *args, **attributes):
        _capture_log('debug', body, attributes, args=args)

    def info(self, body, *args, **attributes):
        _capture_log('info', body, attributes, args=args)

    def warning(self, body, *args, **attributes):
        _capture_log('warn', body, attributes, args=args)

    def error(self, body, *args, **attributes):
        _capture_log('error', body, attributes, args=args)

    def fatal(self, body, *args, **attributes):
        _capture_log('fatal', body, attributes, args=args)

    warn = warning
    critical = fatal

    def exception(self, body, *args, **attributes):
        """An error log carrying the exception being handled, like ``logging.Logger.exception``."""
        _capture_log('error', body, attributes, args=args, exc_info=sys.exc_info())

    def log(self, level, body, *args, **attributes):
        """Log at a stdlib level number (``logging.INFO``) or a level name (``'info'``, ``'WARNING'``)."""
        _capture_log(level, body, attributes, args=args)

    # Keep the stdlib logger's configuration methods working so existing setup code does not break.
    _STDLIB_CONFIG = frozenset(['setLevel', 'getEffectiveLevel', 'isEnabledFor', 'addHandler',
                                'removeHandler', 'hasHandlers', 'addFilter', 'removeFilter',
                                'handlers', 'filters', 'level', 'name', 'propagate', 'disabled'])

    def __getattr__(self, name):
        if name in Logger._STDLIB_CONFIG:
            return getattr(logging.getLogger('cronitor'), name)
        raise AttributeError(name)


logger = Logger()


# events

def _capture_exception(exc, monitor=None, series=None, level='error', tags=None, extra=None,
                       env=None, api_key=None, mechanism='generic', handled=True):
    try:
        exc_info = _exc_info(exc)
        if exc_info is None:
            return None
        event = _base_event(level, monitor, series, tags, extra, env)
        event['exception'] = {'values': _exception_values(exc_info, mechanism, handled)}
        return _submit_event(event, api_key)
    except Exception as e:
        _log.warning('Cronitor could not capture an exception: %s', e)
        return None


def _capture_message(message, level='info', monitor=None, series=None, tags=None, extra=None,
                     env=None, api_key=None):
    try:
        event = _base_event(level, monitor, series, tags, extra, env)
        event['message'] = {'formatted': _truncate(_safe_str(message), MAX_MESSAGE_LENGTH)}
        return _submit_event(event, api_key)
    except Exception as e:
        _log.warning('Cronitor could not capture a message: %s', e)
        return None


def _submit_event(event, api_key):
    if ingest.submit_event(event, api_key=api_key):
        return event['event_id']
    return None


def _exc_info(exc):
    if exc is None:
        exc_info = sys.exc_info()
    elif isinstance(exc, BaseException):
        exc_info = (type(exc), exc, exc.__traceback__)
    elif isinstance(exc, tuple) and len(exc) == 3:
        exc_info = exc
    else:
        _log.warning('Cronitor capture_exception() expects an exception, got %s', type(exc).__name__)
        return None
    if exc_info[0] is None or exc_info[1] is None:
        return None
    return exc_info


def _binding(monitor, series, env):
    """Resolve monitor, series and env: explicit values first, then the enclosing job."""
    job = _current_job.get()
    if job is not None and (monitor is None or monitor == job.monitor):
        monitor = job.monitor
        if series is None:
            series = job.series
        if env is None:
            env = job.env
    return monitor, series, env or cronitor.environment


def _base_event(level, monitor, series, tags, extra, env):
    user_tags = dict(tags or {})
    if monitor is None:
        monitor = user_tags.get(MONITOR_TAG)
    if series is None:
        series = user_tags.get(SERIES_TAG)
    monitor, series, env = _binding(monitor, series, env)

    bound = {}
    if monitor is not None:
        bound[MONITOR_TAG] = monitor
    if series is not None:
        bound[SERIES_TAG] = series
    service = user_tags.get(SERVICE_TAG) or cronitor.service
    if service:
        bound[SERVICE_TAG] = service
    event_tags = {}
    for key, value in list(bound.items()) + list(user_tags.items()):
        key = _truncate(_safe_str(key), MAX_TAG_KEY_LENGTH)
        if key in event_tags or len(event_tags) >= MAX_TAGS:
            continue
        event_tags[key] = _truncate(_safe_str(value), MAX_TAG_VALUE_LENGTH)

    event = {
        'event_id': uuid.uuid4().hex,
        'timestamp': ingest.format_timestamp(),
        'platform': 'python',
        'level': EVENT_LEVELS.get(_safe_str(level).lower(), 'error'),
        'server_name': _hostname(),
        'tags': event_tags,
        'extra': dict(extra or {}),
        'sdk': ingest.sdk_info(),
    }
    if cronitor.release:
        event['release'] = _safe_str(cronitor.release)
    if env:
        event['environment'] = _safe_str(env)
    return event


def _walk_chain(exc_info):
    """Yield (type, value, tb) newest first, following __cause__, then __context__."""
    exc_type, exc_value, tb = exc_info
    seen = set()
    while exc_type is not None and exc_value is not None and id(exc_value) not in seen:
        yield exc_type, exc_value, tb
        seen.add(id(exc_value))
        if exc_value.__cause__ is not None:
            cause = exc_value.__cause__
        elif not exc_value.__suppress_context__:
            cause = exc_value.__context__
        else:
            cause = None
        if cause is None:
            break
        exc_type, exc_value, tb = type(cause), cause, cause.__traceback__


def _exception_values(exc_info, mechanism, handled):
    chain = []
    for link in _walk_chain(exc_info):
        chain.append(link)
        if len(chain) >= MAX_CHAINED_EXCEPTIONS:
            break
    values = []
    for exc_type, exc_value, tb in reversed(chain):
        values.append({
            'type': getattr(exc_type, '__name__', _safe_str(exc_type)),
            'value': _truncate(_safe_str(exc_value), MAX_VALUE_LENGTH),
            'module': _type_module(exc_type),
            'mechanism': {'type': mechanism, 'handled': handled},
            'stacktrace': {'frames': _frames(tb)},
        })
    return values


def _type_module(exc_type):
    module = getattr(exc_type, '__module__', None)
    if module in ('builtins', '__builtin__', 'exceptions'):
        return None
    return module


def _frames(tb):
    """Frames oldest first, the crash site last. Very deep stacks keep both ends."""
    entries = list(traceback.walk_tb(tb))
    if len(entries) > MAX_FRAMES:
        half = MAX_FRAMES // 2
        entries = entries[:half] + entries[-half:]
    return [_frame(frame, lineno) for frame, lineno in entries]


def _frame(frame, lineno):
    code = frame.f_code
    path = code.co_filename or '<unknown>'
    module = frame.f_globals.get('__name__')
    abs_path = path if path.startswith('<') else os.path.abspath(path)
    pre_context, context_line, post_context = _source_context(path, lineno, frame.f_globals)
    return {
        'filename': _filename_for_module(module, abs_path),
        'abs_path': abs_path,
        'function': code.co_name,
        'module': module,
        'lineno': lineno,
        'context_line': context_line,
        'pre_context': pre_context,
        'post_context': post_context,
        'in_app': _in_app(abs_path),
    }


def _source_context(path, lineno, module_globals):
    try:
        lines = linecache.getlines(path, module_globals)
    except Exception:
        lines = []
    if not lines or not lineno or lineno > len(lines):
        return [], None, []
    index = lineno - 1
    clean = [_truncate(line.rstrip('\r\n'), MAX_LINE_LENGTH) for line in
             lines[max(0, index - CONTEXT_LINES):index + CONTEXT_LINES + 1]]
    offset = index - max(0, index - CONTEXT_LINES)
    return clean[:offset], clean[offset], clean[offset + 1:]


def _filename_for_module(module, abs_path):
    """A path relative to the top-level package, like Sentry, e.g. myapp/jobs/nightly.py."""
    if not module or abs_path.startswith('<'):
        return abs_path
    try:
        if abs_path.endswith('.pyc'):
            abs_path = abs_path[:-1]
        base_module = module.split('.', 1)[0]
        if base_module == module:
            return os.path.basename(abs_path)
        base_path = getattr(sys.modules.get(base_module), '__file__', None)
        if not base_path:
            return abs_path
        return abs_path.split(base_path.rsplit(os.sep, 2)[0], 1)[-1].lstrip(os.sep)
    except Exception:
        return abs_path


_stdlib_prefixes = None


def _library_prefixes():
    global _stdlib_prefixes
    if _stdlib_prefixes is None:
        prefixes = set()
        paths = sysconfig.get_paths()
        for name in ('stdlib', 'platstdlib'):
            path = paths.get(name)
            if path:
                for candidate in (path, os.path.realpath(path)):
                    prefixes.add(candidate.rstrip(os.sep) + os.sep)
        _stdlib_prefixes = tuple(prefixes)
    return _stdlib_prefixes


def _in_app(abs_path):
    if abs_path.startswith('<'):
        return not abs_path.startswith('<frozen')
    if 'site-packages' in abs_path or 'dist-packages' in abs_path:
        return False
    return not abs_path.startswith(_library_prefixes())


# logs

def _capture_log(level, body, attributes, args=(), exc_info=None, extra_attributes=None, timestamp=None):
    try:
        level = _level_name(level)
        template = _safe_str(body)
        params = dict(attributes)
        plain = params.pop('attributes') if isinstance(params.get('attributes'), dict) else {}
        attrs = {}
        text = template
        if args:
            text, attrs = _percent_format(template, args)
            attrs.update(params)
        elif params and '{' in template:
            try:
                text = template.format(**params)
                attrs['sentry.message.template'] = template
                for key, value in params.items():
                    attrs['sentry.message.parameter.{}'.format(key)] = value
            except (KeyError, IndexError, ValueError, AttributeError, TypeError):
                text = template
                attrs.update(params)
        else:
            attrs.update(params)
        attrs.update(plain)
        if exc_info is not None and exc_info[0] is not None:
            attrs.update(_exception_attributes(*exc_info))
        if extra_attributes:
            attrs.update(extra_attributes)
        record = _log_record(level, text, attrs, timestamp)
        return ingest.submit_log(record)
    except Exception as e:
        _log.warning('Cronitor could not capture a log record: %s', e)
        return False


def _percent_format(template, args):
    """Format like the stdlib's LogRecord.getMessage(), keeping the template on error.

    Returns (text, attributes): the parameters, and the template when it formatted.
    """
    if len(args) == 1 and isinstance(args[0], Mapping) and args[0]:
        args = args[0]
    params = args.items() if isinstance(args, Mapping) else enumerate(args)
    attrs = {'sentry.message.parameter.{}'.format(key): value for key, value in params}
    try:
        text = template % args
    except Exception:
        return template, attrs
    attrs['sentry.message.template'] = template
    return text, attrs


def _exception_attributes(exc_type, exc_value, tb):
    stacktrace = ''.join(traceback.format_exception(exc_type, exc_value, tb))
    return {
        'exception.type': getattr(exc_type, '__name__', _safe_str(exc_type)),
        'exception.message': _safe_str(exc_value),
        # keep the end, where the crash site and the message are
        'exception.stacktrace': stacktrace[-MAX_TEXT_ATTRIBUTE_LENGTH:],
    }


_LOG_LEVEL_NAMES = {'trace': 'trace', 'debug': 'debug', 'info': 'info', 'warn': 'warn', 'warning': 'warn',
                    'error': 'error', 'fatal': 'fatal', 'critical': 'fatal'}


def _level_name(level):
    """A log level from a name (``'info'``, ``'WARNING'``) or a stdlib level number (``logging.INFO``)."""
    if isinstance(level, int):
        return _log_level(level)
    name = _safe_str(level).lower()
    if name in _LOG_LEVEL_NAMES:
        return _LOG_LEVEL_NAMES[name]
    # a custom level registered with logging.addLevelName
    number = logging.getLevelName(name.upper())
    return _log_level(number) if isinstance(number, int) else 'info'


def _log_record(level, body, attributes, timestamp=None):
    user = dict(attributes)
    monitor, series, env = _binding(user.pop(MONITOR_TAG, None), user.pop(SERIES_TAG, None), None)
    service = user.pop(SERVICE_TAG, None) or cronitor.service

    attrs = {
        'sentry.severity_number': LOG_SEVERITY[level],
        'sentry.severity_text': level,
        'sentry.sdk.name': ingest.SDK_NAME,
        'sentry.sdk.version': ingest.SDK_VERSION,
        'server.address': _hostname(),
    }
    if env:
        attrs['sentry.environment'] = _safe_str(env)
    if cronitor.release:
        attrs['sentry.release'] = _safe_str(cronitor.release)
    if monitor is not None:
        attrs[MONITOR_TAG] = _safe_str(monitor)
    if series is not None:
        attrs[SERIES_TAG] = _safe_str(series)
    if service:
        attrs[SERVICE_TAG] = _safe_str(service)
    for key, value in user.items():
        key = _truncate(_safe_str(key), MAX_ATTRIBUTE_KEY_LENGTH)
        if key in attrs or len(attrs) >= MAX_ATTRIBUTES:
            continue
        attrs[key] = value

    return {
        'timestamp': time.time() if timestamp is None else float(timestamp),
        'level': level,
        'body': _truncate(body, MAX_LOG_BODY_LENGTH),
        'attributes': {key: _typed(value, MAX_TEXT_ATTRIBUTE_LENGTH if key in TEXT_ATTRIBUTES
                                   else MAX_ATTRIBUTE_VALUE_LENGTH)
                       for key, value in attrs.items()},
    }


def _typed(value, max_length):
    if isinstance(value, bool):
        return {'value': value, 'type': 'boolean'}
    if isinstance(value, int):
        return {'value': value, 'type': 'integer'}
    if isinstance(value, float) and math.isfinite(value):
        return {'value': value, 'type': 'double'}
    if not isinstance(value, str):
        value = _safe_repr(value)
    return {'value': _truncate(value, max_length), 'type': 'string'}


# logging integration

_LOGGING_LEVELS = (
    (logging.CRITICAL, 'fatal'),
    (logging.ERROR, 'error'),
    (logging.WARNING, 'warn'),
    (logging.INFO, 'info'),
    (logging.DEBUG, 'debug'),
)
# records about sending must not be sent, or a failing transport would feed itself
_INTERNAL_LOGGERS = ('cronitor.ingest', 'cronitor.capture')


def _log_level(levelno):
    for threshold, name in _LOGGING_LEVELS:
        if levelno >= threshold:
            return name
    return 'trace'


class LogHandler(logging.Handler):
    """A logging.Handler that ships records to Cronitor as structured logs.

    Records are batched by the background transport. A record with exc_info
    carries the formatted traceback in the ``exception.stacktrace`` attribute;
    no separate exception event is sent.

    The default level is INFO, so a root logger at DEBUG does not ship every
    library's debug lines; pass ``level=logging.DEBUG`` to include them.
    """

    def __init__(self, level=logging.INFO):
        super(LogHandler, self).__init__(level)

    def emit(self, record):
        if ingest.in_worker_thread() or record.name.startswith(_INTERNAL_LOGGERS):
            return
        try:
            attrs = {
                'logger.name': record.name,
                'code.file.path': record.pathname,
                'code.line.number': record.lineno,
                'code.function.name': record.funcName,
            }
            if record.args and isinstance(record.msg, str):
                attrs['sentry.message.template'] = record.msg
                params = record.args.items() if isinstance(record.args, dict) else enumerate(record.args)
                for key, value in params:
                    attrs['sentry.message.parameter.{}'.format(key)] = value
            if record.exc_info and record.exc_info[0] is not None:
                attrs.update(_exception_attributes(*record.exc_info))
            log = _log_record(_log_level(record.levelno), record.getMessage(), attrs, timestamp=record.created)
            ingest.submit_log(log)
        except Exception:
            self.handleError(record)


# helpers

def _hostname():
    try:
        return socket.gethostname()
    except Exception:
        return ''


def _truncate(value, length):
    return value if len(value) <= length else value[:length]


def _safe_str(value):
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return _safe_repr(value)


def _safe_repr(value):
    try:
        return repr(value)
    except Exception:
        return '<unrepresentable %s>' % type(value).__name__
