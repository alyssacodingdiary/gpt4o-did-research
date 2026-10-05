#!/usr/bin/env python3
"""Historical Reddit collection and offline normalization (Python 3.10+)."""
import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://arctic-shift.photon-reddit.com/api'
LIMIT = 100
UTC = dt.timezone.utc
FIELDS = sorted(['record_id', 'record_type', 'subreddit', 'created_utc', 'created_date', 'author_id', 'author_namespace', 'post_id', 'parent_id', 'title', 'text', 'deleted_text', 'score', 'source_sha256'])


def now():
    return dt.datetime.now(UTC).isoformat()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tmp.replace(path)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def epoch(value):
    if isinstance(value, (int, float)) or re.fullmatch(r'\d+(?:\.0+)?', str(value)):
        return int(float(value))
    d = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return int(d.timestamp())


def key_bytes(path, create=True):
    path = Path(path)
    if not path.exists() and create:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(secrets.token_bytes(32))
    key = path.read_bytes()
    if len(key) < 32:
        raise ValueError('Author key must have at least 32 bytes')
    return key


def read_plan(path):
    p = load(path)
    if p['kind'] not in ('comments', 'posts') or p['end_utc'] <= p['start_utc']:
        raise ValueError('Invalid kind or time window')
    if not p['subreddits'] or any(not re.fullmatch(r'[A-Za-z0-9_]{1,50}', s) for s in p['subreddits']):
        raise ValueError('Invalid subreddit list')
    return p


def normalize(raw, plan, source, key):
    sub = raw.get('subreddit') or raw.get('source_community')
    if not sub or str(sub).lower() not in {x.lower() for x in plan['subreddits']}:
        return None
    stamp = epoch(raw.get('created_utc') or raw.get('created_date'))
    if not plan['start_utc'] <= stamp < plan['end_utc']:
        return None
    comment = plan['kind'] == 'comments'
    ident = raw.get('id') or raw.get('comment_id_platform' if comment else 'post_id_platform') or raw.get('comment_id' if comment else 'submission_id')
    if not ident:
        raise ValueError('Eligible row has no stable record ID')
    ident = str(ident)
    if ident.startswith(('t1_', 't3_')):
        ident = ident[3:]
    if not re.fullmatch('[a-zA-Z0-9]+', ident):
        raise ValueError('Malformed record ID')
    oldhash = raw.get('author_id_hash') or raw.get('author_hash')
    author = raw.get('author')
    namespace, author_id = '', ''
    if oldhash:
        namespace = plan.get('legacy_author_namespace') or ('unknown_source:' + source)
        author_id = str(oldhash)
    elif author and author not in ('[deleted]', '[removed]'):
        namespace = 'hmac-sha256:' + hashlib.sha256(key).hexdigest()[:16]
        author_id = hmac.new(key, str(author).lower().strip().encode(), hashlib.sha256).hexdigest()
    text = raw.get('body', raw.get('body_text', '')) if comment else raw.get('selftext', '')
    return {'record_id': ('t1_' if comment else 't3_') + ident, 'record_type': 'comment' if comment else 'post',
            'subreddit': str(sub), 'created_utc': stamp, 'created_date': dt.datetime.fromtimestamp(stamp, UTC).date().isoformat(),
            'author_id': author_id, 'author_namespace': namespace,
            'post_id': raw.get('link_id') or raw.get('post_id_platform') or raw.get('submission_id') or (ident if not comment else ''),
            'parent_id': raw.get('parent_id') or raw.get('parent_comment_id_platform') or '',
            'title': raw.get('title') or '', 'text': text or '', 'deleted_text': text in ('[removed]', '[deleted]'),
            'score': raw.get('score', raw.get('comment_score')), 'source_sha256': source}


class Sink:
    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        db = self.out / 'working.sqlite'
        if db.exists():
            raise FileExistsError('Fresh output directory required: ' + str(db))
        self.db = sqlite3.connect(db)
        self.db.execute('CREATE TABLE records (id TEXT PRIMARY KEY, payload TEXT, semantic TEXT)')
        self.duplicates = self.conflicts = self.eligible = 0
        self.conf = (self.out / 'conflicts.jsonl').open('w', encoding='utf-8')

    def add(self, row):
        if row is None:
            return
        self.eligible += 1
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        semantic = json.dumps({k: v for k, v in row.items() if k != 'source_sha256'}, ensure_ascii=False, sort_keys=True)
        old = self.db.execute('SELECT semantic FROM records WHERE id=?', (row['record_id'],)).fetchone()
        if old:
            self.duplicates += 1
            if old[0] != semantic:
                self.conflicts += 1
                self.conf.write(json.dumps({'record_id': row['record_id'], 'retained': 'first_observed', 'other_source_sha256': row['source_sha256']}) + '\n')
        else:
            self.db.execute('INSERT INTO records VALUES (?,?,?)', (row['record_id'], payload, semantic))

    def finish(self, coverage, source_kind):
        self.db.commit()
        daily, by_sub, namespaces = Counter(), Counter(), Counter()
        first, last, count = None, None, 0
        with (self.out / 'records.jsonl').open('w', encoding='utf-8') as jf, (self.out / 'records.csv').open('w', encoding='utf-8', newline='') as cf:
            writer = csv.DictWriter(cf, fieldnames=FIELDS, lineterminator='\n');writer.writeheader()
            for (value,) in self.db.execute('SELECT payload FROM records ORDER BY id'):
                r = json.loads(value)
                writer.writerow(r);jf.write(value + '\n');count += 1
                by_sub[r['subreddit']] += 1;daily[(r['subreddit'], r['created_date'])] += 1
                namespaces[r['author_namespace']] += 1
                first = r['created_utc'] if first is None else min(first, r['created_utc'])
                last = r['created_utc'] if last is None else max(last, r['created_utc'])
        with (self.out / 'daily_counts.csv').open('w', encoding='utf-8', newline='') as f:
            w = csv.writer(f, lineterminator='\n');w.writerow(['subreddit', 'date_utc', 'observed_records'])
            for (sub, day), n in sorted(daily.items()):w.writerow([sub, day, n])
        summary = {'unique_records': count, 'eligible_observations': self.eligible, 'duplicate_observations': self.duplicates,
                   'version_conflicts': self.conflicts, 'communities': dict(sorted(by_sub.items())),
                   'earliest_epoch_utc': first, 'latest_epoch_utc': last, 'author_namespaces': dict(sorted(namespaces.items())),
                   'coverage_statuses': dict(Counter(c['status'] for c in coverage)), 'source_kind': source_kind,
                   'platform_census_proven': False, 'DID_ready': False,
                   'note': 'Coverage describes supplied files/service queries only; absent rows/days are not proven zero activity.'}
        dump(self.out / 'coverage.json', coverage);dump(self.out / 'summary.json', summary)
        self.conf.close();self.db.close();(self.out / 'working.sqlite').unlink()
        return summary


def file_rows(path):
    path = Path(path)
    if path.suffix.lower() == '.parquet':
        import pyarrow.parquet as pq
        for batch in pq.ParquetFile(path).iter_batches(batch_size=4096):yield from batch.to_pylist()
    elif path.suffix.lower() == '.zst':
        import zstandard
        with path.open('rb') as f, zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(f, read_across_frames=True) as stream:
            with io.TextIOWrapper(stream, encoding='utf-8') as text:
                for line in text:
                    if line.strip():yield json.loads(line)
    else:
        with path.open(encoding='utf-8-sig', newline='') as f:
            if path.suffix.lower() == '.csv':yield from csv.DictReader(f)
            else:
                for line in f:
                    if line.strip():yield json.loads(line)


def convert(args):
    plan = read_plan(args.plan);key = key_bytes(args.key_file)
    out = Path(args.out);out.mkdir(parents=True, exist_ok=False);dump(out / 'plan.json', plan)
    manifest = {'started_utc': now(), 'source_type': 'local_archives', 'files': [], 'key_id': hashlib.sha256(key).hexdigest()[:16]}
    sink = Sink(out / 'normalized');coverage = [];failed = False
    for filename in args.inputs:
        p = Path(filename).resolve();digest = sha(p)
        info = {'input_path': str(p), 'sha256': digest, 'bytes': p.stat().st_size, 'rows_read': 0, 'status': 'archive_file_exhausted'}
        try:
            for raw in file_rows(p):info['rows_read'] += 1;sink.add(normalize(raw, plan, digest, key))
        except Exception as exc:
            info['status'] = 'parse_or_read_error';info['error'] = f'{type(exc).__name__}: {exc}';failed = True
        manifest['files'].append(info);coverage.append(info);dump(out / 'manifest.json', manifest)
        if failed:break
    result = sink.finish(coverage, 'local_archives');manifest.update(finished_utc=now(), fully_read=not failed)
    dump(out / 'manifest.json', manifest);print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if failed else 0


def classify(status, body, cell):
    lo, hi = cell['start'], cell['end']
    try:payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):payload = None
    if status != 200:
        if status == 422 and b'slow down' in body.lower():return 'server_busy', []
        if status == 422 and b'timed out' in body.lower() and hi - lo > 1:return 'split', []
        return 'http_error', []
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):return 'invalid_payload', []
    rows = payload['data']
    seen_ids = set()
    try:
        for r in rows:
            if not isinstance(r, dict) or not r.get('id') or str(r.get('subreddit', '')).lower() != cell['subreddit'].lower():return 'invalid_payload', []
            if str(r['id']) in seen_ids:return 'invalid_payload', []
            seen_ids.add(str(r['id']))
            if not lo - 1 <= epoch(r['created_utc']) <= hi:return 'invalid_payload', []
    except (KeyError, TypeError, ValueError):return 'invalid_payload', []
    if len(rows) >= LIMIT:return ('split' if hi - lo > 1 else 'saturated_second'), rows
    return 'api_exhausted', rows


def children(cell):
    mid = (cell['start'] + cell['end']) // 2
    return [{**cell, 'end': mid}, {**cell, 'start': mid}]


def cells(plan):
    result = []
    for sub in plan['subreddits']:
        start = plan['start_utc']
        while start < plan['end_utc']:
            end = min(start + 86400, plan['end_utc']);result.append({'subreddit': sub, 'start': start, 'end': end});start = end
    return result


def api(args):
    plan = read_plan(args.plan);key = key_bytes(args.key_file);out = Path(args.out)
    keyid = hashlib.sha256(key).hexdigest()[:16]
    if (out / 'state.json').exists():
        state = load(out / 'state.json')
        if load(out / 'plan.json') != plan or state['key_id'] != keyid:raise ValueError('Resume requires identical plan and author key')
    else:
        out.mkdir(parents=True, exist_ok=False);(out / 'responses').mkdir();dump(out / 'plan.json', plan)
        state = {'started_utc': now(), 'key_id': keyid, 'queue': cells(plan), 'coverage': [], 'requests': []}
        dump(out / 'state.json', state)
    state['stopped_reason'] = None;previous = 0
    for _ in range(args.max_requests):
        if not state['queue']:break
        cell = state['queue'][0];pause = args.min_interval - (time.monotonic() - previous)
        if pause > 0:time.sleep(pause)
        previous = time.monotonic()
        params = {'subreddit': cell['subreddit'], 'after': cell['start'] - 1, 'before': cell['end'], 'limit': LIMIT, 'sort': 'asc',
                  'fields': 'id,subreddit,created_utc,author,score,' + ('body,link_id,parent_id' if plan['kind'] == 'comments' else 'title,selftext,url,num_comments')}
        url = BASE + '/' + plan['kind'] + '/search?' + urllib.parse.urlencode(params)
        rec = {'cell': cell, 'url': url, 'requested_at_utc': now()}
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'reddit-history-collector/1.0 (research archive client)'})
            with urllib.request.urlopen(req, timeout=args.timeout) as r:status = r.status;body = r.read(8 * 1024 * 1024 + 1);headers = dict(r.headers)
        except urllib.error.HTTPError as exc:status = exc.code;body = exc.read(8 * 1024 * 1024 + 1);headers = dict(exc.headers)
        except Exception as exc:status = None;body = b'';headers = {};rec['error'] = f'{type(exc).__name__}: {exc}'
        path = 'responses/' + f'{len(state["requests"]):06d}.json';(out / path).write_bytes(body);state['queue'].pop(0)
        outcome, _rows = classify(status, body, cell) if status is not None else ('network_error', [])
        if len(body) > 8 * 1024 * 1024:outcome = 'response_size_limit'
        rec.update(http_status=status, status=outcome, response_file=path, sha256=hashlib.sha256(body).hexdigest(),
                   headers={k: v for k, v in headers.items() if k.lower() in ['date', 'content-type', 'retry-after', 'x-ratelimit-reset', 'x-ratelimit-reset-at']}, finished_at_utc=now())
        state['requests'].append(rec)
        if status in (401, 403, 429) or outcome == 'server_busy':
            state['queue'].insert(0, cell);state['stopped_reason'] = f'HTTP {status} / {outcome}; manual resume only after access/rate-limit/capacity condition resolves'
        elif outcome == 'split':state['queue'] = children(cell) + state['queue']
        else:state['coverage'].append({**cell, 'status': outcome})
        dump(out / 'state.json', state)
        print(json.dumps({'subreddit': cell['subreddit'], 'start': cell['start'], 'http_status': status, 'status': outcome, 'pending': len(state['queue'])}), flush=True)
        if state['stopped_reason']:break
    dump(out / 'state.json', state)
    return 0


def replay(args):
    run = Path(args.run);plan = read_plan(run / 'plan.json');state = load(run / 'state.json');key = key_bytes(args.key_file, create=False)
    if hashlib.sha256(key).hexdigest()[:16] != state['key_id']:raise ValueError('Wrong author key')
    for rec in state['requests']:
        if sha(run / rec['response_file']) != rec['sha256']:raise ValueError('Raw-response hash mismatch')
    out = Path(args.out);out.mkdir(parents=True, exist_ok=False);sink = Sink(out)
    for rec in state['requests']:
        body = (run / rec['response_file']).read_bytes()
        outcome, rows = classify(rec['http_status'], body, rec['cell'])
        if outcome in ('api_exhausted', 'split', 'saturated_second'):
            for raw in rows:sink.add(normalize(raw, plan, rec['sha256'], key))
    result = sink.finish(state['coverage'] + [{**c, 'status': 'pending'} for c in state['queue']], 'arctic_shift_api')
    dump(out / 'output_hashes.json', {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()})
    print(json.dumps(result, ensure_ascii=False, indent=2));return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__);sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan');p.add_argument('--subreddits', nargs='+', required=True);p.add_argument('--start', required=True);p.add_argument('--end', required=True);p.add_argument('--kind', choices=['comments', 'posts'], default='comments');p.add_argument('--out', required=True)
    p = sub.add_parser('convert');p.add_argument('--plan', required=True);p.add_argument('--inputs', nargs='+', required=True);p.add_argument('--out', required=True);p.add_argument('--key-file', required=True)
    p = sub.add_parser('api');p.add_argument('--plan', required=True);p.add_argument('--out', required=True);p.add_argument('--key-file', required=True);p.add_argument('--max-requests', type=int, default=20);p.add_argument('--min-interval', type=float, default=3.0);p.add_argument('--timeout', type=float, default=30.0)
    p = sub.add_parser('replay');p.add_argument('--run', required=True);p.add_argument('--out', required=True);p.add_argument('--key-file', required=True)
    args = parser.parse_args()
    if args.cmd == 'plan':
        if Path(args.out).exists():raise FileExistsError('Do not overwrite a frozen plan')
        p = {'version': 1, 'subreddits': sorted(set(s.removeprefix('r/') for s in args.subreddits)), 'start_utc': epoch(args.start), 'end_utc': epoch(args.end), 'kind': args.kind,
             'window': '[start,end) UTC', 'keyword_filter': None, 'legacy_author_namespace': None}
        if p['end_utc'] <= p['start_utc']:raise ValueError('End must follow start')
        dump(args.out, p);read_plan(args.out);print(json.dumps(p, indent=2));return 0
    if args.cmd == 'api' and (args.max_requests < 1 or args.min_interval < 1 or args.timeout <= 0):raise ValueError('Invalid request budget, interval or timeout')
    return {'convert': convert, 'api': api, 'replay': replay}[args.cmd](args)


if __name__ == '__main__':raise SystemExit(main())
