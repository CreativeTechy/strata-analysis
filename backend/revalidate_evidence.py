"""Rebuild published Evidence using frozen documents and the configured model.

Defaults to a read-only plan. Use --apply to publish new generations; previous
generations and their analyst reviews remain available for inspection.
"""
import argparse
import json

import config  # loads the configured provider and database environment
import db
from services.evidence.workspace import RULES_VERSION, generate_for_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--all', action='store_true', help='Rebuild even current results, reusing relevance cache')
    args = parser.parse_args()
    rows = db.fetch_all('''select distinct ec.run_id,ec.project_id
        from evidence_claims ec join evidence_run_status ers on ers.run_id=ec.run_id
        where ec.active and (ec.rules_version<>%s or %s) and ers.status<>'running'
          and (%s::text is null or ec.run_id=%s)
        order by ec.project_id,ec.run_id''', (RULES_VERSION, args.all, args.run_id, args.run_id))
    failed = 0
    for row in rows:
        print(json.dumps({'run_id': row['run_id'], 'project_id': row['project_id'], 'action': 'rebuild' if args.apply else 'plan'}), flush=True)
        if args.apply:
            try:
                result = generate_for_run(row['run_id'], row['project_id'])
                print(json.dumps(result, default=str), flush=True)
            except Exception as exc:
                failed += 1
                print(json.dumps({'run_id': row['run_id'], 'error': str(exc)}), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
