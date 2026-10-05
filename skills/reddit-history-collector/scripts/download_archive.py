#!/usr/bin/env python3
"""Download one authorized HTTPS archive with a byte budget and provenance."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True);p.add_argument('--out', required=True)
    p.add_argument('--max-bytes', required=True, type=int);p.add_argument('--sha256')
    a = p.parse_args();out = Path(a.out);partial = out.with_name(out.name + '.partial');url = urllib.parse.urlsplit(a.url)
    if url.scheme != 'https' or url.username or url.password:raise ValueError('Use a public HTTPS publisher URL without embedded credentials')
    if out.exists() or partial.exists():raise FileExistsError('Fresh output required')
    if a.max_bytes < 1:raise ValueError('Positive byte budget required')
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {'source_url': a.url, 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'status': 'pending', 'bytes': 0};h = hashlib.sha256()
    try:
        req = urllib.request.Request(a.url, headers={'User-Agent': 'reddit-history-collector/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            meta['http_status'] = r.status;meta['resolved_url'] = r.url;size = r.headers.get('Content-Length')
            if size and int(size) > a.max_bytes:raise ValueError('Publisher file exceeds requested byte budget')
            with partial.open('xb') as f:
                while True:
                    b = r.read(1024 * 1024)
                    if not b:break
                    meta['bytes'] += len(b)
                    if meta['bytes'] > a.max_bytes:raise ValueError('Download byte budget exceeded')
                    f.write(b);h.update(b)
            if size and meta['bytes'] != int(size):raise ValueError('Incomplete download')
        meta['sha256'] = h.hexdigest()
        if a.sha256 and meta['sha256'] != a.sha256.lower():raise ValueError('Published SHA-256 mismatch')
        partial.replace(out);meta['status'] = 'downloaded'
    except Exception as exc:
        meta['status'] = 'failed';meta['error'] = f'{type(exc).__name__}: {exc}'
        if isinstance(exc, urllib.error.HTTPError):meta['http_status'] = exc.code;meta['retry_after'] = exc.headers.get('Retry-After')
    meta['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    out.with_name(out.name + '.provenance.json').write_text(json.dumps(meta, indent=2) + '\n')
    print(json.dumps({k: meta[k] for k in ['status', 'bytes']}, indent=2))
    return 0 if meta['status'] == 'downloaded' else 2


if __name__ == '__main__':raise SystemExit(main())
