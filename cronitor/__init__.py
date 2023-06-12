import logging
import os
from datetime import datetime
from functools import wraps
import sys
import requests
import yaml
from yaml.loader import SafeLoader
import difflib
import re

from .monitor import Monitor, YAML

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# configuration variables
api_key = os.getenv('CRONITOR_API_KEY', None)
api_version = os.getenv('CRONITOR_API_VERSION', None)
environment = os.getenv('CRONITOR_ENVIRONMENT', None)
config = os.getenv('CRONITOR_CONFIG', None)
celerybeat_only = False

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

# include_output is deprecated in favor of log_output and can be removed in 5.0 release
def job(key, env=None, log_output=True, include_output=True):
    def wrapper(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            start = datetime.now().timestamp()

            monitor = Monitor(key, env=env)
            # use start as the series param to match run/fail/complete correctly
            monitor.ping(state=State.RUN, series=start)
            try:
                out = func(*args, **kwargs)
            except Exception as e:
                duration = datetime.now().timestamp() - start
                monitor.ping(state=State.FAIL, message=str(e), metrics={'duration': duration}, series=start)
                raise e

            duration = datetime.now().timestamp() - start
            message = str(out) if all([log_output, include_output]) else None
            monitor.ping(state=State.COMPLETE, message=message, metrics={'duration': duration}, series=start)
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
    if not this.config:
        raise ConfigValidationError("Must set a path to config file e.g. cronitor.config = './cronitor.yaml'")

    config = read_config(output=True)
    try:
        monitors = Monitor.put(monitors=config, rollback=rollback, format=YAML)
        job_count = len(monitors.get('jobs', []))
        check_count = len(monitors.get('checks', []))
        heartbeat_count = len(monitors.get('heartbeats', []))
        total_count = sum([job_count, check_count, heartbeat_count])
        logger.info('{} monitor{} {}'.format(total_count, 's' if total_count != 1 else '', 'validated.' if rollback else 'synced.',))
        return True
    except (yaml.YAMLError, ConfigValidationError, APIValidationError, APIError, AuthenticationError) as e:
        logger.error(e)
        return False

def read_config(path=None, output=False):
    this.config = path or this.config
    if not this.config:
        raise ConfigValidationError("Must include a path to config file e.g. cronitor.read_config('./cronitor.yaml')")

    with open(this.config, 'r') as conf:
        data = yaml.load(conf, Loader=SafeLoader)
        if output:
            return data

def prepare_data_for_diff(dict):
    return yaml.dump(dict, default_flow_style=False, sort_keys=True).split("\n")


def diff_config(path, output=False):
    monitor_id_regex = r'^    [a-zA-Z0-9_-]+\:'
    monitor_name_regex = r'^      name\:'
    remote_config = yaml.load(Monitor.as_yaml(), Loader=SafeLoader)
    local_config = read_config(path, output=True)
    diff_result = difflib.ndiff(prepare_data_for_diff(remote_config), prepare_data_for_diff(local_config))
    buffer = ""
    current_monitor = ""
    current_name = ""
    for line in diff_result:
        if re.match(monitor_id_regex, line):
            if buffer != "" and current_name != "" and current_monitor:
                print(f'Target: {current_name}({current_monitor})')
                print(buffer)
                buffer = ""
            current_monitor = line.replace(':', '').strip()
        if re.match(monitor_name_regex, line):
            current_name = line.replace('name: ', '').strip()
        elif current_monitor and line.startswith("-"):
            buffer += f"Remote : {line}\n"
        elif current_monitor and line.startswith("+"):
            buffer += f"Local  : {line}\n"
        elif current_monitor and line.startswith("?"):
            buffer += f"Diff   : {line}\n"
    if output:
        return diff_result
