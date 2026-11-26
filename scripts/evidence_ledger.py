"""Offline evidence ledger for saved supplier results (evidence-ledger-v1).

    python3 -S scripts/evidence_ledger.py eval-results/live-30oct/wessex_mill-result.json [more results ...]
    python3 -S scripts/evidence_ledger.py RESULT.json --output new-ledger.json

Reads saved result files only and prints JSON, or writes it to a new --output file. It makes no network, model or
browser call, never rewrites an input, refuses to overwrite an existing file, and asserts no shipping rule.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scout.evidence_ledger import ledger_for_result  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description='Offline evidence ledger for saved supplier results.')
    p.add_argument('results', nargs='+', help='saved result JSON files (read only)')
    p.add_argument('--output', help='new file to write; must not exist and must not be an input')
    a = p.parse_args(argv)
    inputs = [Path(x).resolve() for x in a.results]
    out = {'inputs': []}
    for path in inputs:
        data = path.read_bytes()
        ledger = ledger_for_result(json.loads(data.decode('utf-8')))
        out['inputs'].append({'path': str(Path(path).relative_to(Path.cwd())) if path.is_relative_to(Path.cwd())
                              else str(path), 'file_sha256': hashlib.sha256(data).hexdigest(), **ledger})
    text = json.dumps(out, ensure_ascii=False, indent=1, sort_keys=False) + '\n'
    if not a.output:
        sys.stdout.write(text)
        return 0
    target = Path(a.output).resolve()
    if target in inputs:
        sys.exit('refusing to write over an input file: %s' % a.output)
    if target.exists():
        sys.exit('refusing to overwrite an existing file: %s' % a.output)
    with open(target, 'x', encoding='utf-8') as f:
        f.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
