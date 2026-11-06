"""Bounded tracked-file pattern scan; reports paths/line numbers, never matched secrets."""
from pathlib import Path
import re
import subprocess

PATTERNS = [re.compile(pattern) for pattern in (
    rb'(?:ghp_|github_pat_|oc_sk_)[A-Za-z0-9_]{20,}',
    rb'sk-[A-Za-z0-9_-]{30,}',
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    rb'AKIA[0-9A-Z]{16}',
)]


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z']).split(b'\0')
    findings = []
    checked = 0
    for raw in names:
        if not raw:
            continue
        path = Path(raw.decode())
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        content = path.read_bytes()
        if b'\0' in content:
            continue
        checked += 1
        for index, line in enumerate(content.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                findings.append(f'{path}:{index}')
    print(f'Bounded pattern scan: {checked} tracked text files; {len(findings)} findings.')
    for finding in findings:
        print(finding)
    print('This does not establish absence of all credentials or sensitive data.')
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
