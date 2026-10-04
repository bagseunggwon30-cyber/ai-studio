"""Restore every altered byte after UI evidence checks in a disposable preview."""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from studio.util import atomic_write_text, atomic_write_json, clean_child_env, no_window_flags, read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--session', default='evidence')
    parser.add_argument('--task', default='T0001')
    args = parser.parse_args()
    preview = args.root.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not preview.is_relative_to(temp) or not preview.name.startswith('studio-test-'):
        raise ValueError('Disposable TempStudio directory required')
    with urlopen('http://127.0.0.1:8798/api/state', timeout=10) as response:
        if json.load(response)['studio']['fake'] is not True:
            raise ValueError('Existing fake preview required')
    if not re.fullmatch(r'T[0-9]+', args.task):
        raise ValueError('Disposable task ID required')
    task = read_json(preview / 'data/tasks' / (args.task + '.json'))
    qa = (preview / 'data/qa' / task['qa']['qa_id']).resolve()
    if not qa.is_relative_to(preview / 'data/qa') or task['status'] != 'awaiting_approval':
        raise ValueError('Current disposable candidate required')
    receipt, answer = qa / 'evidence.json', qa / 'snapshot/docs/answer.txt'
    original_receipt, original_answer = receipt.read_bytes(), answer.read_bytes()
    reports = []
    def browser(code=None):
        command = ['node', str(args.cli), '-s=' + args.session, 'run-code']
        command += [code] if code else ['--filename', 'tools/dev/workbench_evidence_finish.js']
        result = subprocess.run(command, cwd=ROOT, env=clean_child_env(), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=180, creationflags=no_window_flags())
        output = result.stdout.decode('utf-8', 'replace')
        if result.returncode:
            raise RuntimeError(output[-2500:])
        if code is None:
            report = json.loads(output.split('### Result\n', 1)[1].split('\n### Ran', 1)[0])
            reports.append(report)
            print(json.dumps({'phase': report['phase'], 'status': report['status'], 'checks': report['count']}), flush=True)
    try:
        for phase in ('altered-receipt', 'altered-snapshot', 'restore-and-approve'):
            atomic_write_text(receipt, original_receipt.decode("utf-8"))
            atomic_write_text(answer, original_answer.decode("utf-8"))
            if phase == 'altered-receipt':
                value = json.loads(original_receipt)
                value['tests'][0]['ok'] = False
                atomic_write_json(receipt, value)
            elif phase == 'altered-snapshot':
                atomic_write_text(answer, '99\n')
            browser("async(page) => {await page.evaluate(phase => localStorage.setItem('workbench-evidence-qa-phase', phase), " + json.dumps(phase) + ");}")
            browser()
    finally:
        atomic_write_text(receipt, original_receipt.decode("utf-8"))
        atomic_write_text(answer, original_answer.decode("utf-8"))
    atomic_write_json(ROOT / 'docs/verification/workbench-evidence-browser-finish.json', {
        'status': 'pass', 'phases': reports, 'checks': sum(r['count'] for r in reports),
        'restored_receipt': receipt.read_bytes() == original_receipt,
        'restored_snapshot': answer.read_bytes() == original_answer,
        'real_model_calls': 0, 'production_writes': 0})


if __name__ == '__main__':
    main()
