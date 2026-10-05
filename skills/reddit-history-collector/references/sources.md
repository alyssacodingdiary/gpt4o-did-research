# Sources and recovery

- Archive processing: https://github.com/Watchful1/PushshiftDumps
- Monthly releases: https://github.com/ArthurHeitmann/arctic_shift/releases
- API documentation: https://github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md
- API base: https://arctic-shift.photon-reddit.com
- Comment search: /api/comments/search; submission search: /api/posts/search.

Check releases at execution time. Monthly archives may lag the desired event month. A release listing does not prove files were downloaded. API availability and performance are not guaranteed; its documentation recommends dumps for massive processing.

## Recovered historical pattern

A prior 100,000-comment CSV retained six subreddit-specific *_comments.zst source paths and 2025-01-01 through 2025-12-31 dates. A later million-row Parquet explicitly identified an Academic Torrents subreddit archive as its method. This establishes an archive-processing route, not the exact early conversation date, torrent ID, original command, sampling seed or inclusion probability.

A separate supplement used Arctic Shift parameters subreddit, after, before, sort=asc, limit=100 and fields. It retained only the first 100 comments per month. That convenience sample is not complete pagination and should not be used to measure historical activity or inactivity.

## Bulk workflow

1. Resolve a current publisher release; record source URL, retrieval time, date range, filename, size, version and published checksum when available.
2. Prefer subreddit-specific archives when practical. For torrents, inspect the file list and select required archives only. Retain metadata and selection logs.
3. Use download_archive.py for direct HTTPS files, or a standard client for torrent-only distribution. This skill does not automate torrent seeding or install a torrent client.
4. Stream .zst JSONL with reddit_history.py convert. CSV, JSONL and optional Parquet are also accepted.
5. Audit daily/community counts and parser failures. File exhaustion is not a population-completeness claim.

## Use and sharing

Record source conditions and project authorization. Public access does not grant blanket redistribution rights. Keep raw texts, source author identifiers and private keys in the authorized project workspace. Follow project deletion/update requirements before publication. The code license does not license Reddit content. The Arctic Shift client does not need a Reddit OAuth key, but does not confer Reddit research approval.
