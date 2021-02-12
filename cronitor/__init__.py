import logging
import os
from datetime import datetime
from functools import wraps
import sys
import yaml
from yaml.loader import SafeLoader

from .monitor import Monitor

logging.basicConfig()
logger = logging.getLogger(__name__)

CONFIG_KEYS = (
    'api_key',
    'api_version',
    'environment',
)
MONITOR_TYPES = ('job', 'event', 'synthetic')
YAML_KEYS = CONFIG_KEYS + tuple(map(lambda t: '{}s'.format(t), MONITOR_TYPES))

# configuration variables
api_key = os.getenv('CRONITOR_API_KEY', None)
api_version = os.getenv('CRONITOR_API_VERSION', None)
environment = os.getenv('CRONITOR_ENVIRONMENT', None)
config = os.getenv('CRONITOR_CONFIG', None)

# this is a pointer to the module object instance itself.
this = sys.modules[__name__]
if this.config:
    this.read_config() # set config vars contained within

class MonitorNotFound(Exception):
    pass

class ConfigValidationError(Exception):
    pass

class APIValidationError(Exception):
    pass

class AuthenticationError(Exception):
    pass

class APIError(Exception):
    pass

class State(object):
    OK = 'ok'
    RUN = 'run'
    COMPLETE = 'complete'
    FAIL = 'fail'

def job(key):
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            start = datetime.now().timestamp()

            monitor = Monitor(key)
            # use start as the series param to match run/fail/complete correctly
            monitor.ping(state=State.RUN, series=start)
            try:
                out = func(*args, **kwargs)
            except Exception as e:
                duration = datetime.now().timestamp() - start
                monitor.ping(state=State.FAIL, message=str(e), metrics={'duration': duration}, series=start)
                raise e

            duration = datetime.now().timestamp() - start
            monitor.ping(state=State.COMPLETE, metrics={'duration': duration}, series=start)
            return out

        return wrapped
    return wrapper

def generate_config():
    config = this.config or './cronitor.yaml'
    with open(config, 'w') as conf:
        conf.writelines(Monitor.as_yaml())

def validate_config():
    return apply_config(rollback=True)

def apply_config(rollback=False):
    try:
        conf = _parse_config()
        monitors = Monitor.put(conf.get('monitors'), rollback=rollback)
        print("{} monitors {}".format(len(monitors), 'validated.' if rollback else 'synced to Cronitor.'))
    except (ConfigValidationError, APIValidationError, APIError, AuthenticationError) as e:
        logger.error(e)

def read_config(path=None, output=False):
    this.config = path or this.config
    if not this.config:
        raise ConfigValidationError("Must include a path to config file e.g. cronitor.read_config('./cronitor.yaml')")

    with open(this.config, 'r') as conf:
        data = yaml.load(conf, Loader=SafeLoader)

        if 'api_key' in data:
            this.api_key = data['api_key']
        if 'api_version' in data:
            this.api_version = data['api_version']
        if 'environment' in data:
            this.environment = data['environment']
        if output:
            return data

def _parse_config():
    data = read_config(output=True)
    monitors = []
    for k in data.keys():
        if k not in YAML_KEYS:
            raise ConfigValidationError("Invalid configuration variable: %s" % k)

    for t in MONITOR_TYPES:
        to_parse = None
        plural_t = t + 's'
        if t in data:
            to_parse = data[t]
        elif plural_t in data:
            to_parse = data[plural_t]

        if to_parse:
            if type(to_parse) != dict:
                raise ConfigValidationError("A dict with keys corresponding to monitor keys is expected.")
            for key, m in to_parse.items():
                m['key'] = key
                m['type'] = t
                monitors.append(m)

    data['monitors'] = monitors
    return data
