# Reddit History Collector — Codex Skill

Collect historical Reddit comments and posts for reproducible research with archive imports, bounded Arctic Shift queries, coverage audits and offline replay.

## 中文说明

大量历史数据优先使用按月份或社区发布的 `.zst` 归档，缺少的时间段再使用 Arctic Shift API 补采。RSS 只适合近期发现。这个 skill 保存原始响应、SHA-256、失败与待采区间，按稳定 ID 去重，并保留重复版本冲突。

它不会把抓取失败记成零活动，不会把社区进入等同产品流失，也不会自动宣称数据已足够支持 DID 或 agency 结论。

## Install in Codex

Tell Codex:

> Install the skill at `skills/reddit-history-collector` from https://github.com/alyssacodingdiary/gpt4o-did-research

Then ask:

> Use $reddit-history-collector to collect historical comments for r/ChatGPT and r/ClaudeAI from 2026-08-01 inclusive to 2026-10-01 exclusive. Prefer archives, use the API for missing intervals, and report coverage before analysis.

The installed skill's [SKILL.md](skills/reddit-history-collector/SKILL.md) contains the operating workflow. Platform permissions and service availability still apply.

## Local command-line use

Python 3.10+; CSV/JSONL and API workflows need no third-party packages. Install `zstandard` for `.zst`, and `pyarrow` only for Parquet.

```bash
python -m pip install zstandard
python skills/reddit-history-collector/scripts/reddit_history.py plan --subreddits ChatGPT ClaudeAI --start 2026-08-01 --end 2026-10-01 --out runs/plan.json
python skills/reddit-history-collector/scripts/reddit_history.py api --plan runs/plan.json --out runs/api --key-file private/author.key --max-requests 20
python skills/reddit-history-collector/scripts/reddit_history.py replay --run runs/api --out runs/replayed --key-file private/author.key
```

For existing historical files:

```bash
python skills/reddit-history-collector/scripts/reddit_history.py convert --plan runs/plan.json --inputs archive/ChatGPT_comments.zst archive/ClaudeAI_comments.zst --out runs/imported --key-file private/author.key
```

Run the API command again with the same plan/output/key to resume **pending** intervals. It stops on access blocks, rate limits and explicit server capacity messages. Other failed intervals remain recorded as failures; they are not silently retried or counted as empty.

Use fresh output directories for conversions and replays. Keep the author key outside public code and reuse it for compatible raw-username sources. Existing unknown author hashes stay source-specific.

## What is included

- UTC half-open date windows and fixed community frames.
- Full-page interval bisection, with unresolved one-second timestamp ties flagged.
- Checkpointed request logs, original responses and byte hashes.
- Streaming `.zst`, CSV, JSONL and optional Parquet imports.
- Stable-ID deduplication, first-version retention and conflict logs.
- Offline reconstruction, daily counts and explicit unknown coverage.
- Budget-limited HTTPS archive downloader with checksum validation.
- Synthetic regression tests for boundaries, saturation, failures, resume, integrity, duplicates and multi-frame zstd.

The tool does not bundle Reddit data, OAuth credentials, a torrent client, a statistical DID estimator or sentiment/agency labels.

## Validation

The initial release was checked against an existing 100,000-comment research input: all 100,000 unique IDs were retained and normalized outputs reproduced byte-for-byte. This is an import/replay check, not a new 100,000-record live harvest. Synthetic tests are clearly separated from observed data. A live September 2026 API probe on 2026-10-05 returned HTTP 422 with a server capacity/timeout message; the client does not promise continuing API availability.

```bash
python -m unittest discover -s skills/reddit-history-collector/scripts -p 'test_*.py' -v
```

## Sources and interpretation

- [Arctic Shift API documentation](https://github.com/ArthurHeitmann/arctic_shift/blob/master/api/README.md)
- [Arctic Shift monthly releases](https://github.com/ArthurHeitmann/arctic_shift/releases)
- [Watchful1 archive-processing examples](https://github.com/Watchful1/PushshiftDumps)
- [Coverage and DID boundaries](skills/reddit-history-collector/references/coverage.md)

Service exhaustion is not proof of a Reddit census. A balanced sample or monthly first-N page cannot establish population inactivity. Historical DID still needs comparable observation windows, credible exposure/control definitions, validated outcomes and appropriate inference.

## License

MIT for this repository's original code. This license grants no rights to Reddit content or third-party archives. Keep texts, author identifiers, source logs and research keys in an authorized private project workspace; follow applicable source and deletion requirements.
