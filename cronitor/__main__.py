import argparse
import os
import sys

from .monitor import Monitor


def main():
    parser = argparse.ArgumentParser(prog="cronitor",
                                     description='Send status messages to Cronitor ping API.')  # noqa
    parser.add_argument('--pingApiKey', '-a', type=str,
                        default=os.getenv('CRONITOR_PING_API_KEY', os.getenv('CRONITOR_AUTH_KEY')),
                        help='Auth Key from Account page')
    parser.add_argument('--id', '-i', type=str,
                        default=os.getenv('CRONITOR_ID', os.getenv('CRONITOR_CODE')),
                        help='Monitor Id to take action upon')
    # alias for id. deprecated.
    parser.add_argument('--code', '-c', type=str,
                        default=os.getenv('CRONITOR_CODE'),
                        help='DEPRECATED: Code for Monitor to take action upon. Alias of Id.')
    parser.add_argument('--msg', '-m', type=str, default='',
                        help='Optional message to send with ping/fail')

    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument('--run', '-r', action='store_true',
                       help='Send a run event')
    group.add_argument('--complete', '-C', action='store_true',
                       help='Send a complete event')
    group.add_argument('--tick', '-t', action='store_true',
                       help='Send an tick event')
    group.add_argument('--fail', '-f', action='store_true',
                       help='Send a fail event')
    group.add_argument('--ok', '-o', action='store_true',
                       help='Send an ok event')
    group.add_argument('--pause', '-p', type=str, default=24,
                       help='Pause a monitor')

    args = parser.parse_args()

    if args.id is None and args.code is None:
        print('A monitorId must be supplied using the --id flag or setting the CRONITOR_ID enviromenment variable.')
        parser.print_help()
        sys.exit(1)

    monitor = Monitor(id=args.id, ping_api_key=args.pingApiKey)

    ret = None
    if args.run:
        ret = monitor.run(message=args.msg)
    elif args.complete:
        ret = monitor.complete(message=args.msg)
    elif args.tick:
        ret = monitor.tick(message=args.msg)
    elif args.fail:
        ret = monitor.fail(message=args.msg)
    elif args.ok:
        ret = monitor.ok(message=args.msg)
    elif args.pause:
        ret = monitor.pause(args.pause)

    return ret


if __name__ == '__main__':
    main()
