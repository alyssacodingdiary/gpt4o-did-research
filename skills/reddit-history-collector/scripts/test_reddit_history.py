"""Synthetic regression tests; none of these records are Reddit observations."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

import reddit_history as rh
import download_archive as dl


class Response(io.BytesIO):
    status = 200
    url = 'https://publisher.example/archive.zst'
    def __init__(self, body):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.root = Path(self.tmp.name)
        self.plan = {'kind': 'comments', 'subreddits': ['Example'], 'start_utc': 100, 'end_utc': 200}
        self.cell = {'subreddit': 'Example', 'start': 100, 'end': 200}
        self.key = b'unit-test-only-not-a-project-key!'
    def tearDown(self):self.tmp.cleanup()
    def row(self, i='a', stamp=150):return {'id': i, 'subreddit': 'Example', 'created_utc': stamp, 'author': 'synthetic_user', 'body': 'Synthetic test record'}

    def test_half_open_boundaries(self):
        self.assertIsNone(rh.normalize(self.row(stamp=99), self.plan, 'source', self.key))
        self.assertIsNotNone(rh.normalize(self.row(stamp=100), self.plan, 'source', self.key))
        self.assertIsNone(rh.normalize(self.row(stamp=200), self.plan, 'source', self.key))

    def test_saturated_page_and_timestamp_ties(self):
        body = json.dumps({'data': [self.row(str(i)) for i in range(100)]}).encode()
        self.assertEqual(rh.classify(200, body, self.cell)[0], 'split')
        self.assertEqual(rh.classify(200, body, {**self.cell, 'start': 150, 'end': 151})[0], 'saturated_second')
        self.assertEqual(rh.children(self.cell), [{'subreddit': 'Example', 'start': 100, 'end': 150}, {'subreddit': 'Example', 'start': 150, 'end': 200}])

    def test_errors_not_empty_activity(self):
        self.assertEqual(rh.classify(200, b'{"error":"database failure"}', self.cell)[0], 'invalid_payload')
        self.assertEqual(rh.classify(200, b'{"data":[]}', self.cell)[0], 'api_exhausted')
        self.assertEqual(rh.classify(429, b'limit', self.cell)[0], 'http_error')
        self.assertEqual(rh.classify(422, b'Query timed out', self.cell)[0], 'split')
        self.assertEqual(rh.classify(422, b'{"data":null,"error":"Timeout. Maybe slow down a bit"}', self.cell)[0], 'server_busy')
        self.assertEqual(rh.classify(200, json.dumps({'data':[self.row(),self.row()]}).encode(), self.cell)[0], 'invalid_payload')

    def test_duplicate_versions_are_reported(self):
        sink = rh.Sink(self.root/'normalized')
        a = rh.normalize(self.row(), self.plan, 'one', self.key)
        sink.add(a);sink.add({**a,'source_sha256':'two'});sink.add({**a,'text':'Changed synthetic text'})
        r = sink.finish([], 'test_fixture')
        self.assertEqual((r['unique_records'],r['duplicate_observations'],r['version_conflicts']), (1,2,1))

    def test_rate_stop_resume_and_offline_replay(self):
        plan = self.root/'plan.json';rh.dump(plan,self.plan);key = self.root/'key';key.write_bytes(self.key)
        args = SimpleNamespace(plan=plan,key_file=key,out=self.root/'api',max_requests=2,min_interval=1,timeout=3)
        error = urllib.error.HTTPError('https://example.invalid',429,'limit',{'Retry-After':'60'},io.BytesIO(b'limit'))
        with patch.object(rh.urllib.request,'urlopen',side_effect=error) as fetch,contextlib.redirect_stdout(io.StringIO()):rh.api(args)
        self.assertEqual(fetch.call_count,1);self.assertEqual(len(rh.load(args.out/'state.json')['queue']),1)
        args.max_requests=1;body=json.dumps({'data':[self.row()]}).encode()
        with patch.object(rh.urllib.request,'urlopen',return_value=Response(body)),contextlib.redirect_stdout(io.StringIO()):rh.api(args)
        self.assertEqual(len(rh.load(args.out/'state.json')['queue']),0)
        with patch.object(rh.urllib.request,'urlopen',side_effect=AssertionError('No network in replay')),contextlib.redirect_stdout(io.StringIO()):
            for name in ['one','two']:rh.replay(SimpleNamespace(run=args.out,out=self.root/name,key_file=key))
        self.assertEqual((self.root/'one/records.jsonl').read_bytes(),(self.root/'two/records.jsonl').read_bytes())
        f=args.out/'responses/000001.json';f.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):rh.replay(SimpleNamespace(run=args.out,out=self.root/'tampered',key_file=key))

    def test_zstd_multiple_frames(self):
        try:import zstandard as z
        except ImportError:self.skipTest('Optional zstandard unavailable')
        f=self.root/'two_frames.zst';f.write_bytes(b''.join(z.ZstdCompressor().compress((json.dumps(self.row(i))+'\n').encode()) for i in ['a','b']))
        self.assertEqual([r['id'] for r in rh.file_rows(f)],['a','b'])

    def test_download_integrity_and_size_budget(self):
        body=b'synthetic-archive-bytes';dest=self.root/'archive.zst'
        argv=['download_archive.py','--url','https://publisher.example/archive.zst','--out',str(dest),'--max-bytes','100','--sha256',hashlib.sha256(body).hexdigest()]
        with patch('sys.argv',argv),patch.object(dl.urllib.request,'urlopen',return_value=Response(body)),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(dl.main(),0)
        self.assertEqual(dest.read_bytes(),body)
        argv[4]=str(self.root/'budget.zst');argv[6]='1'
        with patch('sys.argv',argv),patch.object(dl.urllib.request,'urlopen',return_value=Response(body)),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(dl.main(),2)
        self.assertFalse((self.root/'budget.zst').exists())


if __name__=='__main__':unittest.main()
