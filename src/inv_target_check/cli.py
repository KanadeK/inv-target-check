import argparse
import json
import sys

from . import __version__
from .core import AuditError, audit


def main(argv=None):
    parser = argparse.ArgumentParser(description='Validate a Sphinx v2 inventory against a local HTML tree.')
    parser.add_argument('inventory', help='objects.inv file')
    parser.add_argument('root', help='built documentation root')
    parser.add_argument('--base-url', help='public directory URL mapped to root, ending in /')
    parser.add_argument('--allow-external', action='store_true', help='report external targets without failing')
    parser.add_argument('--json', action='store_true', help='emit the complete JSON report')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        report = audit(args.inventory, args.root, base_url=args.base_url, allow_external=args.allow_external)
    except (OSError, RuntimeError, AuditError) as exc:
        print('inv-target-check: ' + json.dumps(str(exc), ensure_ascii=True), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print(f"{report['entries']} targets: " + ', '.join(f'{v} {k}' for k, v in report['summary'].items()))
        for item in report['results']:
            if item['status'] != 'ok':
                print(f"line {item['line']}: {item['code']} " + json.dumps(item['name']) + ' -> ' + json.dumps(item['target']))
        print('PASS' if report['passed'] else 'FAIL')
    return 0 if report['passed'] else 1
