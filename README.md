# Cronitor Python Library
[![Build Status](https://travis-ci.org/cronitorio/cronitor-python.svg?branch=master)](https://travis-ci.org/cronitorio/cronitor-python)

[Cronitor](https://cronitor.io/) provides dead simple monitoring for cron jobs, daemons, data pipelines, queue workers, and anything else that can send or receive an HTTP request. The Cronitor Python library provides convenient access to the Cronitor API from applications written in Python.

## Documentation
See our [API docs](https://cronitor.io/docs/api) for a detailed reference information about the APIs this library uses for configuring monitors and sending telemetry pings.

## Installation

```
pip install cronitor
```

## Usage

The package needs to be configured with your account's `API key`, which is available on the [account settings](https://cronitor.io/settings) page. You can also optionally specify an `Api Version` (default: account default) and `Environment` (default: account default).

These can be supplied using the environment variables `CRONITOR_API_KEY`, `CRONITOR_API_VERSION`, `CRONITOR_ENVIRONMENT` or set directly on the cronitor object.

```python
import cronitor

cronitor.api_key = 'apiKey123
cronitor.api_version = '2020-10-01'
cronitor.environment = 'staging'
```

You can also use a YAML config file to manage all of your monitors (_see Create and Update Monitors section below_). The path to this file can be supplied using the enviroment variable `CRONITOR_CONFIG` or call `cronitor.read_config()`.

```python
import cronitor
cronitor.read_config('./path/to/cronitor.yaml')
```


### Integrate with Cron/Scheduled Task Libraries

This package provides a lightweight wrapper for integrating with libraries like Celery's [Beat Scheduler](https://docs.celeryproject.org/en/v5.0.5/reference/celery.beat.html) or the popular [schedule](https://github.com/dbader/schedule) package to monitor any job.

#### celery example
```python
import cronitor
from celery import Celery

app = Celery()

app.conf.beat_schedule = {
  'run-me-every-minute': {
    'task': 'tasks.every_minute_celery_task',
    'schedule': 60
  }
}

@app.task
@cronitor.job("run-me-every-minute")
def every_minute_celery_task():
    print("running a background job with celery...")

```

#### schedule example
```python
import schedule

@cronitor.job("hourly-schedule-job")
def job():
  print("running a background job...")

schedule.every().hour.do(job)
```

The `@cronitor.job` decorator will send telemetry pings when your function begins and exits. If an error is raised a `fail` ping will be sent. Monitors will be automatically provisioned with the provided key the first time a ping is received.


### Sending Telemetry Pings

If you simply want to send a heartbeat event or want finer control over when/how [telemetry pings](https://cronitor.io/docs/ping-api) are sent,
you can create a monitor instance and call `.ping` directly.

```python
import cronitor

monitor = cronitor.Monitor('heartbeat-monitor');
monitor.ping()

# optional params can be passed as an object.
# for a complete list see https://cronitor.io/docs/ping-api
monitor.ping({
    state: 'run|complete|fail|ok', # run|complete|fail used to measure lifecycle of a job, ok used for manual reset only.
    env: '', # the environment this is running in (e.g. staging, production)
    message: '', # message that will be displayed in alerts as well as monitor activity panel on your dashboard.
    metrics: {
        duration: 100, # how long the job ran (complete|fail only). cronitor will calculate this when not provided
        count: 4500, # if your job is processing a number of items you can report a count
        error_count: 10 # the number of errors that occurred while this job was running
    }
});
```

### Pause, Reset, Delete

```python
import cronitor

monitor = cronitor.Monitor('heartbeat-monitor');

monitor.pause(24) # pause alerting for 24 hours
monitor.unpause() # alias for .pause(0)
monitor.ok() # manually reset to a passing state alias for monitor.ping({state: ok})
monitor.delete() # destroy the monitor
```

## Create and Update Monitors

You can create monitors programatically using the `Monitor` object.
For details on all of the attributes that can be set, see the [Monitor API](https://cronitor.io/docs/monitor-api) documentation.


```python
import cronitor

monitors = cronitor.Monitor.put(
  {
    'type': 'job',
    'key': 'send-customer-invoices',
    'schedule': '0 0 * * *',
    'assertions': [
        'metric.duration < 5 min'
    ],
    'notify': ['devops-alerts-slack']
  },
  {
    'type': 'synthetic',
    'key': 'Orders Api Uptime',
    'schedule': 'every 45 seconds',
    'assertions': [
        'response.code = 200',
        'response.time < 1.5s',
        'response.json "open_orders" < 2000'
    ]
  }
)
```

You can also manage all of your monitors via a YAML config file.
This can be version controlled and synced to Cronitor as part of
a deployment or build process.

```python
import cronitor

cronitor.read_config('./cronitor.yaml'); # parse the yaml file of monitors

cronitor.validate_config(); # send monitors to Cronitor for configuration validation

cronitor.apply_config(); # sync the monitors from the config file to Cronitor
```


The `cronitor.yaml` file accepts the following attributes:

```yaml
api_key: 'optionally read Cronitor api_key from here'
api_version: 'optionally read Cronitor api_version from here'
environment: 'optionally set an environment for telemetry pings'

# configure all of your monitors with type "job"
# you may omit the type attribute and the key
# of each object will be set as the monitor key
jobs:
    nightly-database-backup:
        schedule: 0 0 * * *
        notify:
            - devops-alert-pagerduty
        assertions:
            - metric.duration < 5 minutes

    send-welcome-email:
        schedule: every 10 minutes
        assertions:
            - metric.count > 0
            - metric.duration < 30 seconds

# configure all of your monitors with type "synthetic"
synthetics:
    cronitor-homepage:
        request:
            url: https://cronitor.io
            regions:
                - us-east-1
                - eu-central-1
                - ap-northeast-1
        assertions:
            - response.code = 200
            - response.time < 2s

    cronitor-ping-api:
        request:
            url: https://cronitor.link/ping
        assertions:
            - response.body contains ok
            - response.time < .25s

events:
    production-deploy:
        notify:
            alerts: ['deploys-slack']
            events: true # send alert when the event occurs

```

## Command Line Usage


```bash
>> python -m cronitor -h

usage: cronitor [-h] [--apikey APIKEY] [--key KEY] [--msg MSG]
                (--run | --complete | --fail | --ok | --pause PAUSE)

Send status messages to Cronitor ping API.

optional arguments:
  -h, --help            show this help message and exit
  --authkey AUTHKEY, -a AUTHKEY
                        Auth Key from Account page
  --key KEY, -k KEY     Unique key for the monitor to take ping
  --msg MSG, -m MSG     Optional message to send with ping/fail
  --tick, -t            Call ping on given monitor
  --run, -r             Call ping with state=run on given monitor
  --complete, -C        Call ping with state=complete on given monitor
  --fail, -f            Call ping with state=fail on given monitor
  --pause PAUSE, -P PAUSE
                        Call pause on given monitor
```


## Contributing

Pull requests and features are happily considered! By participating in this project you agree to abide by the [Code of Conduct](http://contributor-covenant.org/version/2/0).

### To contribute

Fork, then clone the repo:

    git clone git@github.com:your-username/cronitor-python.git

Set up your machine:

    pip install -r requirements

Make sure the tests pass:

    pytest

Make your change. Add tests for your change. Make the tests pass:

    pytest


Push to your fork and [submit a pull request]( https://github.com/cronitorio/cronitor-python/compare/)
