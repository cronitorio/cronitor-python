import typing
import datetime
import humanize
import logging
from cronitor import State, Monitor
import cronitor
import sys

logger = logging.getLogger(__name__)
try:
    import celery
    import celery.beat
    from celery.schedules import crontab, schedule, solar
    from celery.signals import beat_init, task_prerun, task_failure, task_success, task_retry

    if typing.TYPE_CHECKING:
        from typing import Dict, List, Union, Optional, Tuple
        import billiard.einfo
        from celery.worker.request import Request
except ImportError:
    logger.error("Cannot use the cronitor.celery module without celery installed")
    sys.exit(1)

# For the signals to properly register, they need to be top-level objects.
# Since they are defined dynamically in initialize(), we have to declare them up top,
# make them global, and override them.
celerybeat_startup = None
ping_monitor_before_task = None
ping_monitor_on_success = None
ping_monitor_on_failure = None
ping_monitor_on_retry = None


def get_headers_from_task(task):  # type: (celery.Task) -> Dict
    headers = task.request.headers or {}
    headers.update(task.request.get('properties', {}).get('application_headers', {}))
    return headers


def initialize(app, celerybeat_only=False, api_key=None):  # type: (celery.Celery, bool, Optional[str]) -> None
    if api_key:
        cronitor.api_key = api_key

    if celerybeat_only:
        cronitor.celerybeat_only = True

    global celerybeat_startup
    global ping_monitor_before_task
    global ping_monitor_on_success
    global ping_monitor_on_failure
    global ping_monitor_on_retry

    def celerybeat_startup(sender, **kwargs):  # type: (celery.beat.Service, Dict) -> None
        scheduler = sender.get_scheduler()  # type: celery.beat.Scheduler
        schedules = scheduler.get_schedule()
        monitors = []  # type: List[Dict[str, str]]

        for name in schedules:
            if name.startswith('celery.'):
                continue
            entry = schedules[name]  # type: celery.beat.ScheduleEntry

            # ignore all celerybeat scheduled events with the Cronitor exclusion header
            headers = entry.options.pop('headers', {})
            if headers.get('x-cronitor-exclude') in (True, 'true', 'True'):
                logger.info("celerybeat entry '{}' ignored per exclusion header".format(name))
                continue

            item = entry.schedule  # type: celery.schedules.schedule
            if isinstance(item, crontab):
                cronitor_schedule = ('{0._orig_minute} {0._orig_hour} {0._orig_day_of_week} {0._orig_day_of_month} '
                                     '{0._orig_month_of_year}').format(item)
            elif isinstance(item, schedule):
                freq = item.run_every  # type: datetime.timedelta
                cronitor_schedule = 'every ' + humanize.precisedelta(freq)
            elif isinstance(item, solar):
                # We don't support solar schedules
                logger.warning("The cronitor-python celery module does not support "
                               "tasks using solar schedules. Task schedule '{}' will "
                               "not be monitored".format(name))
                continue
            else:
                logger.warning("The cronitor-python celery module does not support "
                               "schedules of type `{}`".format(type(item)))
                continue

            monitors.append({
                'type': 'job',
                'key': name,
                'schedule': cronitor_schedule,
            })

            headers.update({
                'x-cronitor-task-origin': 'celerybeat',
                'x-cronitor-celerybeat-name': name,
            })

            app.add_periodic_task(entry.schedule,
                                  # Setting headers in the signature
                                  # works better then in periodic task options
                                  app.tasks.get(entry.task).s().set(headers=headers),
                                  args=entry.args, kwargs=entry.kwargs,
                                  name=entry.name, **(entry.options or {}))

        # To avoid recursion, since restarting celerybeat will result in this
        # signal being called again, we disconnect the signal.
        beat_init.disconnect(celerybeat_startup, dispatch_uid=1)

        # We need to stop and restart celerybeat to get the task updates in place.
        # This isn't ideal, but seems to work.
        sender.stop()
        app.Beat().run()
        logger.debug("[Cronitor] creating monitors: %s", [m['key'] for m in monitors])
        Monitor.put(monitors)

    beat_init.connect(celerybeat_startup, dispatch_uid=1)

    @task_prerun.connect
    def ping_monitor_before_task(sender, **kwargs):  # type: (celery.Task, Dict) -> None
        headers = get_headers_from_task(sender)
        if 'x-cronitor-celerybeat-name' in headers:
            monitor = Monitor(headers['x-cronitor-celerybeat-name'])
        elif not cronitor.celerybeat_only:
            monitor = Monitor(sender.name)
        else:
            return

        monitor.ping(state=State.RUN, series=sender.request.id)

    @task_success.connect
    def ping_monitor_on_success(sender, **kwargs):  # type: (celery.Task, Dict) -> None
        headers = get_headers_from_task(sender)
        if 'x-cronitor-celerybeat-name' in headers:
            monitor = Monitor(headers['x-cronitor-celerybeat-name'])
        elif not cronitor.celerybeat_only:
            monitor = Monitor(sender.name)
        else:
            return

        monitor.ping(state=State.COMPLETE, series=sender.request.id)

    @task_failure.connect
    def ping_monitor_on_failure(sender,  # type: celery.Task
                                task_id,  # type: str
                                exception,  # type: Exception
                                args,  # type: Tuple
                                kwargs,  # type: Dict
                                traceback,
                                einfo,  # type: billiard.einfo.ExceptionInfo
                                **kwargs2  # type: Dict
                                ):
        headers = get_headers_from_task(sender)
        if 'x-cronitor-celerybeat-name' in headers:
            monitor = Monitor(headers['x-cronitor-celerybeat-name'])
        elif not cronitor.celerybeat_only:
            monitor = Monitor(sender.name)
        else:
            return

        monitor.ping(state=State.FAIL, series=sender.request.id, message=str(exception))

    @task_retry.connect
    def ping_monitor_on_retry(sender,  # type: celery.Task
                              request,  # type: celery.worker.request.Request
                              reason,  # type: Union[Exception, str]
                              einfo,  # type: billiard.einfo.ExceptionInfo
                              **kwargs,  # type: Dict
                              ):
        headers = get_headers_from_task(sender)
        if 'x-cronitor-celerybeat-name' in headers:
            monitor = Monitor(headers['x-cronitor-celerybeat-name'])
        elif not cronitor.celerybeat_only:
            monitor = Monitor(sender.name)
        else:
            return

        monitor.ping(state=State.FAIL, series=sender.request.id, message=str(reason))

