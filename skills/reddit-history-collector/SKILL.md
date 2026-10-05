---
name: reddit-history-collector
description: Collect historical Reddit posts and comments from archive dumps or the Arctic Shift API with raw-response preservation, coverage audits, deduplication and offline replay. Use for historical Reddit scraping, 100k or larger datasets, DID/event-study data preparation, source recovery and resuming interrupted collection. Do not treat RSS as a historical census or missing records as product churn.
---

# Reddit historical collection

Use this skill's scripts; write datasets to the user's project directory, never inside the skill or a public repository.

## Choose and freeze the source

1. Inspect existing files and their source_archive/scrape_method fields before trying another endpoint. Read references/sources.md.
2. Prefer monthly or subreddit-specific .zst dumps for large historical windows. Verify current publisher releases, dates, filenames and sizes. Process authorized files with convert.
3. Use Arctic Shift for a bounded historical pilot or missing interval. Read its current official API documentation before a new session. It is a third-party archive service, not Reddit OAuth/PRAW.
4. Keep RSS for recent discovery only. Record snapshot and missingness limits.
5. Freeze communities and UTC dates without sentiment/outcome filtering. Keep event verification and treatment/comparison decisions separate from collection.

## Execute

Use Python 3.10+. API/CSV/JSONL paths use the standard library. Install zstandard for .zst and pyarrow only for Parquet. Record installed versions in the project log.

```bash
python scripts/reddit_history.py plan --subreddits ChatGPT ClaudeAI --start 2026-08-01 --end 2026-10-01 --out project/plan.json
python scripts/reddit_history.py convert --plan project/plan.json --inputs archive/ChatGPT_comments.zst archive/ClaudeAI_comments.zst --out project/archive_run --key-file project/private/author.key
python scripts/reddit_history.py api --plan project/plan.json --out project/api_run --key-file project/private/author.key --max-requests 20
python scripts/reddit_history.py replay --run project/api_run --out project/replayed --key-file project/private/author.key
```

- Treat start as inclusive and end as exclusive, in UTC. Use --kind posts in plan for submissions; collect comments and posts in separate runs.
- Reuse a private project author key for raw-username sources. Never publish the key. Existing unknown hashes retain a source-specific namespace; do not infer cross-year links.
- Run api again with the same plan/output/key to resume queued cells. It retains saved successful responses and verifies plan/key identity. An interrupted request without a saved checkpoint may repeat.
- Stop on 401/403/429 and explicit server requests to slow down, including 422 capacity messages. Read saved Retry-After/rate-limit-reset headers before a later manual resume. Do not rotate hosts, IPs, cookies or identities to evade restrictions.
- Keep request budgets bounded. Full pages trigger interval bisection. Saturated one-second intervals remain unresolved instead of silently losing timestamp ties.
- Preserve the original archives for offline conversion. API replay uses saved responses without network access.

For a verified authorized direct HTTPS archive URL:

```bash
python scripts/download_archive.py --url VERIFIED_PUBLISHER_FILE_URL --out archive/comments.zst --max-bytes 1000000000 --sha256 EXPECTED_SHA256
```

Use fresh outputs. For torrent-only distribution, inventory filenames and sizes with an available standard client, then download only required files following publisher instructions. Do not default to a multi-terabyte download or invent mirror URLs.

## Audit and deliver

Read references/coverage.md. Inspect summary.json, coverage.json, manifest.json/state.json and conflicts.jsonl. Report unique IDs, date/community coverage, successful/failed/pending cells, duplicate versions and author namespaces. Failures and absent rows remain unknown, never zero activity. Do not add a subset sample to its parent count.

Validate offline replay against saved output hashes. A query exhausted in an archive is not a proven Reddit census. A collector cannot establish a causal event, valid counterfactual or agency construct.

Publish only code, documentation, configuration examples and synthetic tests. Keep Reddit texts, author identifiers, keys, unpublished results and machine paths out of public GitHub. Save research data only in the authorized project workspace.
