import argparse
import os
import sys

from .monitor import Monitor


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


if __name__ == '__main__':
    main()
