from __future__ import print_function
import json
import os
import sys
import argparse

import requests


class Monitor(object):
    def __init__(self, api_key=None, auth_key=None, time_zone='UTC'):
        self.api_endpoint = 'https://cronitor.io/v3/monitors'
        self.ping_endpoint = "https://cronitor.link"
        self.api_key = api_key or os.getenv('CRONITOR_API_KEY')
        self.auth_key = auth_key or os.getenv('CRONITOR_AUTH_KEY')
        self.timezone = time_zone

    def create(self, name=None, note=None, notifications=None,
               rules=None, tags=None):
        payload = self.__prepare_payload(tags, name, note,
                                         notifications, rules)
        return self.__create(payload=payload)

    def update(self, name=None, code=None, note=None,
               notifications=None, rules=None, tags=None):
        payload = self.__prepare_payload(tags, name, note,
                                         notifications, rules)
        return self.__update(payload=payload, code=code)

    def delete(self, code):
        return self.__delete(code)

    def get(self, code):
        return self.__get('{0}/{1}'.format(self.api_endpoint, code))

    def run(self, code, msg=''):
        return self.__ping(code, 'run', msg=msg)

    def complete(self, code, msg=''):
        return self.__ping(code, 'complete')

    def failed(self, code, msg=''):
        return self.__ping(code, 'failed', msg=msg)

    def pause(self, code, hours):
        return self.__get('{0}/{1}/pause/{2}'.format(self.api_endpoint,
                                                     code, hours))

    def clone(self, code, name=None):
        return requests.post(self.api_endpoint,
                             auth=(self.api_key, ''),
                             timeout=10,
                             data=json.dumps({"code": code, name: name}),
                             headers={'content-type': 'application/json'})

    def __ping(self, code, method, msg=''):
        params = dict(auth_key=self.auth_key, msg=msg)
        return requests.get(
            '{0}/{1}/{2}'.format(self.ping_endpoint, code, method),
            params=params,
            timeout=10
        )

    def __get(self, url):
        return requests.get(url,
                            timeout=10,
                            auth=(self.api_key, ''),
                            headers={'content-type': 'application/json'}
                            )

    def __create(self, payload):
        return requests.post(self.api_endpoint,
                             auth=(self.api_key, ''),
                             data=json.dumps(payload),
                             headers={'content-type': 'application/json'},
                             timeout=10
                             )

    def __update(self, payload=None, code=None):
        return requests.put('{0}/{1}'.format(self.api_endpoint, code),
                            auth=(self.api_key, ''),
                            data=json.dumps(payload),
                            headers={'content-type': 'application/json'},
                            timeout=10
                            )

    def __delete(self, code):
        return requests.delete('{0}/{1}'.format(self.api_endpoint, code),
                               auth=(self.api_key, ''),
                               headers={'content-type': 'application/json'},
                               timeout=10
                               )

    @staticmethod
    def __prepare_notifications(notifications):
        if notifications:
            return {
                "emails": notifications.get('emails', []),
                "phones": notifications.get('phones', []),
                "hipchat": notifications.get('hipchat', []),
                "pagerduty": notifications.get('pagerduty', []),
                "slack": notifications.get('slack', []),
                "templates": notifications.get('templates', []),
                "webhooks": notifications.get('webhooks', [])
            }
        else:
            return {}

    def __prepare_payload(self, tags, name, note, notifications, rules):
        return {
            "code": "new_monitor",
            "name": name,
            "type": "heartbeat",
            "timezone": self.timezone,
            "notifications": self.__prepare_notifications(notifications),
            "rules": rules or [],
            "tags": tags or [],
            "note": note
        }


def main():
    parser = argparse.ArgumentParser(prog="cronitor",
                     description='Send status messages to Cronitor ping API.')  # noqa
    parser.add_argument('--authkey', '-a', type=str,
                        default=os.getenv('CRONITOR_AUTH_KEY'),
                        help='Auth Key from Account page')
    parser.add_argument('--code', '-c', type=str,
                        default=os.getenv('CRONITOR_CODE'),
                        help='Code for Monitor to take action upon')
    parser.add_argument('--msg', '-m', type=str, default='',
                        help='Optional message to send with ping/fail')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run', '-r', action='store_true',
                       help='Call ping on given Code')
    group.add_argument('--complete', '-C', action='store_true',
                       help='Call complete on given Code')
    group.add_argument('--fail', '-f', action='store_true',
                       help='Call fail on given Code')
    group.add_argument('--pause', '-P', type=str, default=24,
                       help='Call pause on given Code')

    args = parser.parse_args()

    if args.code is None:
        print('A code must be supplied or CRONITOR_CODE ENV var used')
        parser.print_help()
        sys.exit(1)

    monitor = Monitor(auth_key=args.authkey)

    if args.run:
        ret = monitor.run(args.code, msg=args.msg)
    elif args.fail:
        ret = monitor.failed(args.code, msg=args.msg)
    elif args.complete:
        ret = monitor.complete(args.code)
    elif args.pause:
        ret = monitor.pause(args.code, args.pause)

    return ret.raise_for_status()
