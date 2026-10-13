#!/usr/bin/env python3
"""Stay-rule research starter, v1.0 (2026-10-13).

Not a replication of any existing LA result. It audits an archive without
extracting it, or analyzes a researcher-validated balanced canonical panel.
The main estimator is unit-weighted DID with equal weights over observed
snapshots within pre/post periods, conditional on supplied fixed unit weights.
It is NOT Synthetic DID, IPCW, HonestDiD, or a spatial-HAC implementation.

Commands:
  python run_stay_plan.py audit input.zip --out outputs/audit_run
  python run_stay_plan.py analyze canonical.csv --config design.json --out outputs/main_run
  python run_stay_plan.py selftest --out outputs/synthetic_test

Canonical columns (one row per cohort ID x actual snapshot date):
 listing_id,snapshot_date,present,minimum_nights,maximum_nights,treated,hex_id,weight,coverage_ok
Absence must be supplied explicitly after a coverage audit; missing rows are
never inferred to be absent. Original source data are never modified.
"""
from __future__ import annotations
import argparse, csv, gzip, hashlib, io, json, math, platform, stat, sys, zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VERSION = '1.0'
STATES = ['absent', 'unknown_rule', 'short_only', 'flexible', 'long_only']
POLICY_DATES = ['2025-01-07', '2025-01-15', '2025-01-27']
REQUIRED = ['listing_id', 'snapshot_date', 'present', 'minimum_nights', 'maximum_nights',
            'treated', 'hex_id', 'weight', 'coverage_ok']


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_json(obj):
    if isinstance(obj, dict):
        return {str(k): safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json(x) for x in obj]
    if hasattr(obj, 'item'):
        return safe_json(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def write_json(path: Path, data):
    path.write_text(json.dumps(safe_json(data), ensure_ascii=False, indent=2,
                               allow_nan=False), encoding='utf-8')


def make_output(path: Path):
    # Fail closed rather than silently replacing earlier results.
    path.mkdir(parents=True, exist_ok=False)


def audit_archive(src: Path, out: Path):
    if not src.is_file() or not zipfile.is_zipfile(src):
        raise ValueError('Input must be an existing ZIP archive.')
    manifest = {'status': 'ARCHIVE_METADATA_AUDIT_ONLY', 'version': VERSION,
                'source_name': src.name, 'bytes': src.stat().st_size,
                'source_sha256': sha256(src), 'members': []}
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        duplicate_names = [k for k, v in Counter(i.filename for i in infos).items() if v > 1]
        manifest['duplicate_member_names'] = duplicate_names
        for info in infos:
            if info.is_dir():
                continue
            normalized = info.filename.replace('\\', '/')
            p = PurePosixPath(normalized)
            unsafe = (p.is_absolute() or '..' in p.parts or ':' in normalized.split('/')[0]
                      or stat.S_ISLNK(info.external_attr >> 16))
            row = {'member': info.filename, 'uncompressed_bytes': info.file_size,
                   'compressed_bytes': info.compress_size, 'crc32': f'{info.CRC:08x}',
                   'unsafe_path_or_symlink': unsafe, 'encrypted': bool(info.flag_bits & 1)}
            # Header-only reads: no personal review text is emitted. No extraction.
            if not unsafe and not row['encrypted'] and normalized.lower().endswith(('.csv', '.csv.gz', '.tsv')):
                try:
                    with z.open(info) as raw:
                        stream = gzip.GzipFile(fileobj=raw) if normalized.lower().endswith('.gz') else raw
                        text = stream.read(32768).decode('utf-8-sig', errors='replace')
                        delim = '\t' if normalized.lower().endswith('.tsv') else ','
                        row['header'] = next(csv.reader(io.StringIO(text), delimiter=delim), [])
                        row['header_only'] = True
                        row['relevant_fields'] = sorted(set(row['header']) & set(REQUIRED + [
                            'id', 'host_id', 'last_scraped', 'scrape_id', 'date', 'comments',
                            'name', 'description', 'price', 'adjusted_price', 'available',
                            'minimum_minimum_nights', 'maximum_maximum_nights',
                            'minimum_nights_avg_ntm', 'maximum_nights_avg_ntm']))
                except Exception as exc:
                    row['header_error'] = type(exc).__name__ + ': ' + str(exc)
            manifest['members'].append(row)
    manifest['n_files'] = len(manifest['members'])
    manifest['note'] = ('Member names are not verified observation dates. Calendar dates may be stay dates. '
                        'This audit establishes neither row counts, temporal coverage nor actual bookings. '
                        'Keep a real-data manifest restricted: filenames may contain sensitive identifiers.')
    make_output(out)
    write_json(out / 'archive_manifest.json', manifest)
    print(json.dumps({'status': manifest['status'], 'n_files': manifest['n_files'],
                      'sha256': manifest['source_sha256'], 'output': str(out)}, ensure_ascii=False))


def validate_config(cfg):
    if cfg.get('analysis_kind') not in ['exploratory', 'synthetic_test']:
        raise ValueError('Set analysis_kind explicitly to exploratory or synthetic_test. Existing-data analyses are not retroactive preregistrations.')
    for k in ['date_provenance', 'coverage_basis', 'treatment_basis', 'weight_basis']:
        if not isinstance(cfg.get(k), str) or not cfg[k].strip():
            raise ValueError('Missing documented input basis: ' + k)
    pre, post = cfg.get('pre_dates', []), cfg.get('post_dates', [])
    if not pre or not post or len(set(pre + post)) != len(pre + post):
        raise ValueError('Pre/post lists must be nonempty, nonoverlapping actual snapshot dates.')
    for s in pre + post:
        datetime.strptime(s, '%Y-%m-%d')
    if max(pre) >= min(post):
        raise ValueError('All pre dates must precede all post dates.')
    if cfg.get('reference_date') not in pre:
        raise ValueError('reference_date must be one of the pre dates.')
    if cfg.get('primary_threshold') != 28:
        raise ValueError('Protocol primary threshold is 28. Amend the plan explicitly rather than selecting a favorable threshold.')
    if sorted(cfg.get('thresholds', [])) != [28, 30, 31]:
        raise ValueError('Report pre-specified 28,30,31 thresholds.')


def validate_panel(df, cfg):
    import numpy as np
    import pandas as pd
    validate_config(cfg)
    missing = set(REQUIRED) - set(df.columns)
    if missing:
        raise ValueError('Missing canonical fields: ' + ', '.join(sorted(missing)))
    if df.empty:
        raise ValueError('Empty panel.')
    for c in ['listing_id', 'hex_id', 'snapshot_date']:
        if df[c].isna().any() or df[c].astype(str).str.strip().eq('').any():
            raise ValueError('Missing identifier/date: ' + c)
        df[c] = df[c].astype(str)
    parsed = pd.to_datetime(df['snapshot_date'], format='%Y-%m-%d', errors='raise')
    if not parsed.dt.strftime('%Y-%m-%d').eq(df['snapshot_date']).all():
        raise ValueError('Snapshot dates must have canonical YYYY-MM-DD format.')
    if df.duplicated(['listing_id', 'snapshot_date']).any():
        raise ValueError('Duplicate listing x snapshot keys. Resolve provenance; do not arbitrarily retain one.')
    dates = sorted(cfg['pre_dates'] + cfg['post_dates'])
    if set(df.snapshot_date) != set(dates):
        raise ValueError('Data date set differs from locked design. Subset the canonical cohort deliberately, outside this script.')
    count = df.groupby('listing_id').snapshot_date.nunique()
    if not count.eq(len(dates)).all():
        raise ValueError('Incomplete risk-set grid. Missing rows must not be silently coded as absence.')
    for c in ['present', 'treated', 'coverage_ok']:
        df[c] = pd.to_numeric(df[c], errors='raise')
        if not df[c].isin([0, 1]).all():
            raise ValueError(c + ' must be explicit 0/1.')
    if not df.coverage_ok.eq(1).all():
        raise ValueError('Coverage unverified. Do not infer platform absence in unobserved source periods.')
    for c in ['minimum_nights', 'maximum_nights', 'weight']:
        df[c] = pd.to_numeric(df[c], errors='raise')
    if not np.isfinite(df.weight).all() or (df.weight < 0).any():
        raise ValueError('Weights must be finite and nonnegative.')
    for c in ['weight', 'treated', 'hex_id']:
        if not df.groupby('listing_id')[c].nunique(dropna=False).eq(1).all():
            raise ValueError(c + ' must be fixed per listing in this starter.')
    if df.groupby('hex_id').treated.nunique().gt(1).any():
        raise ValueError('Mixed treatment within a hex conflicts with the locked hex treatment design.')
    positive = df.loc[df.weight > 0].copy()
    if set(positive.treated.unique()) != {0, 1}:
        raise ValueError('Both treatment groups require positive-weight support.')
    if positive.groupby('treated').hex_id.nunique().min() < 2:
        raise ValueError('Insufficient independent cluster support even for a descriptive conventional cluster covariance.')
    return positive, dates


def assign_states(df, k):
    import numpy as np
    lo, hi = df.minimum_nights.to_numpy(), df.maximum_nights.to_numpy()
    seen = df.present.to_numpy() == 1
    valid = (np.isfinite(lo) & np.isfinite(hi) & (lo >= 1) & (hi >= lo)
             & (lo == np.floor(lo)) & (hi == np.floor(hi)))
    state = np.full(len(df), 'absent', dtype=object)
    state[seen & ~valid] = 'unknown_rule'
    state[seen & valid & (hi < k)] = 'short_only'
    state[seen & valid & (lo < k) & (hi >= k)] = 'flexible'
    state[seen & valid & (lo >= k)] = 'long_only'
    return state


def group_wls(Y, treated, weights, groups):
    """WLS on individual changes; conditional CR1 covariance across columns.
    This covariance is only a conventional cluster benchmark, not spatial-HAC
    and not a correction for estimating the weights or few common fire shocks.
    """
    import numpy as np
    X = np.column_stack([np.ones(len(treated)), treated])
    w = weights / np.mean(weights)
    if np.linalg.matrix_rank(X) != 2:
        raise ValueError('Treatment regressor is not identified.')
    bread = np.linalg.inv(X.T @ (w[:, None] * X))
    beta = bread @ (X.T @ (w[:, None] * Y))
    resid = Y - X @ beta
    unique = np.unique(groups)
    scores = []
    for g in unique:
        ix = groups == g
        score = X[ix].T @ (w[ix, None] * resid[ix])
        scores.append((bread @ score)[1])
    scores = np.asarray(scores)
    n, G = len(X), len(unique)
    correction = (G / (G - 1)) * ((n - 1) / (n - 2))
    cov = correction * scores.T @ scores
    return beta[1], cov, G


def interval_rows(beta, cov, groups, names):
    import numpy as np
    from scipy.stats import t
    se = np.sqrt(np.maximum(np.diag(cov), 0))
    crit = t.ppf(.975, groups - 1)
    rows = []
    for j, name in enumerate(names):
        p = float(2 * t.sf(abs(beta[j] / se[j]), groups - 1)) if se[j] > 1e-12 else None
        rows.append({'outcome': name, 'estimate': float(beta[j]), 'se_cr1': float(se[j]),
                     'ci_low_cr1': float(beta[j] - crit * se[j]), 'ci_high_cr1': float(beta[j] + crit * se[j]),
                     'p_raw_cr1': p, 'n_clusters': groups,
                     'inference_scope': 'conditional-on-fixed-weights; conventional hex CR1 only'})
    return rows


def holm_two(rows):
    eligible = [r for r in rows if r['threshold'] == 28 and r['outcome'] in ['flexible', 'long_only']]
    for r in rows:
        r['p_holm_primary'] = None
    if len(eligible) == 2 and all(r['p_raw_cr1'] is not None for r in eligible):
        eligible.sort(key=lambda r: r['p_raw_cr1'])
        a = min(1.0, 2 * eligible[0]['p_raw_cr1'])
        eligible[0]['p_holm_primary'] = a
        eligible[1]['p_holm_primary'] = max(a, eligible[1]['p_raw_cr1'])


def analyze(src: Path, config: Path, out: Path, quiet=False):
    import numpy as np
    import pandas as pd
    import scipy
    cfg = json.loads(config.read_text(encoding='utf-8-sig'))
    original = pd.read_csv(src, dtype={'listing_id': str, 'hex_id': str, 'snapshot_date': str})
    df, dates = validate_panel(original.copy(), cfg)
    ids = sorted(df.listing_id.unique())
    unit = df.drop_duplicates('listing_id').set_index('listing_id').loc[ids]
    treated, w, groups = unit.treated.to_numpy(), unit.weight.to_numpy(), unit.hex_id.to_numpy()
    pre_ix = [dates.index(s) for s in cfg['pre_dates']]
    post_ix = [dates.index(s) for s in cfg['post_dates']]
    ref = dates.index(cfg['reference_date'])
    make_output(out)
    all_did, shares, transitions, events = [], [], [], []
    coefficients = {}
    for k in cfg['thresholds']:
        state = pd.Series(assign_states(df, k), index=df.index)
        wide = df.assign(state=state).pivot(index='listing_id', columns='snapshot_date', values='state').loc[ids, dates]
        values = wide.to_numpy()
        ys = np.stack([(values == s).astype(float) for s in STATES], axis=2)
        if not np.allclose(ys.sum(axis=2), 1):
            raise AssertionError('Mutually exclusive state partition failed.')
        delta = ys[:, post_ix, :].mean(axis=1) - ys[:, pre_ix, :].mean(axis=1)
        beta, cov, G = group_wls(delta, treated, w, groups)
        if abs(beta.sum()) > 1e-9:
            raise AssertionError('State effects must sum to zero under the same estimator.')
        coefficients[k] = dict(zip(STATES, beta.tolist()))
        for r in interval_rows(beta, cov, G, STATES):
            r.update(threshold=k, n_ids=len(ids), n_rows=len(df), analysis_kind=cfg['analysis_kind'])
            all_did.append(r)
        pd.DataFrame(cov, index=STATES, columns=STATES).to_csv(out / f'did_vcov_k{k}.csv')
        event_matrix = (ys - ys[:, ref:ref+1, :]).reshape(len(ids), -1)
        eb, ec, eg = group_wls(event_matrix, treated, w, groups)
        labels = [f'{date}:{s}' for date in dates for s in STATES]
        erows = interval_rows(eb, ec, eg, labels)
        for j, row in enumerate(erows):
            row['snapshot_date'], row['outcome'] = dates[j // len(STATES)], STATES[j % len(STATES)]
            row['threshold'], row['reference_date'] = k, cfg['reference_date']
            if row['snapshot_date'] == cfg['reference_date']:
                row['p_raw_cr1'] = None
                row['reference_fixed_zero'] = True
            else:
                row['reference_fixed_zero'] = False
            events.append(row)
        pd.DataFrame(ec, index=labels, columns=labels).to_csv(out / f'event_vcov_k{k}.csv')
        for g in [0, 1]:
            ix = treated == g
            for j, date in enumerate(dates):
                for sidx, s in enumerate(STATES):
                    shares.append({'threshold': k, 'treated': g, 'snapshot_date': date, 'state': s,
                                   'count': int((values[ix, j] == s).sum()), 'n_ids': int(ix.sum()),
                                   'weighted_share': float(np.average(ys[ix, j, sidx], weights=w[ix]))})
            for j in range(1, len(dates)):
                for a in STATES:
                    for b in STATES:
                        mask = ix & (values[:, j-1] == a) & (values[:, j] == b)
                        transitions.append({'threshold': k, 'treated': g, 'from_date': dates[j-1],
                            'to_date': dates[j], 'from_state': a, 'to_state': b,
                            'count': int(mask.sum()), 'share_of_fixed_group': float(w[mask].sum()/w[ix].sum())})
    holm_two(all_did)
    for name, rows in [('did', all_did), ('event_study', events), ('state_shares', shares), ('transitions', transitions)]:
        pd.DataFrame(rows).to_csv(out / (name + '.csv'), index=False)
    policy_columns = {d: [int(t >= d) for t in dates] for d in POLICY_DATES}
    distinct_policy_columns = len(set(tuple(v) for v in policy_columns.values()))
    ess = {str(g): float(w[treated == g].sum()**2 / (w[treated == g]**2).sum()) for g in [0, 1]}
    report = {'version': VERSION, 'analysis_kind': cfg['analysis_kind'],
        'input_sha256': sha256(src), 'config_sha256': sha256(config), 'script_sha256': sha256(Path(__file__)),
        'created_utc': datetime.now(timezone.utc).isoformat(), 'config': cfg,
        'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__, 'scipy': scipy.__version__,
        'n_ids_input': int(original.listing_id.nunique()), 'n_positive_weight_ids': len(ids),
        'n_rows_analyzed': len(df), 'date_list': dates, 'n_clusters': len(set(groups)), 'ess_by_treatment': ess,
        'january_policy_columns': policy_columns, 'n_distinct_policy_columns': distinct_policy_columns,
        'separate_january_effects_identified_by_dates': False if distinct_policy_columns < 3 else 'NOT_ESTABLISHED_BY_RANK_ALONE',
        'state_effects_sum_zero': True, 'coefficients_for_audit': coefficients,
        'warnings': ['No source coverage audit or cohort construction is performed by this estimator.',
                     'This is not a replication of the previously reported LA effect.',
                     'CR1 treats the supplied weights as fixed and does not solve spatial correlation or few fire shocks.',
                     'Rule-based states do not establish bookings, habitability, refugee identity, or housing-use conversion.',
                     'Calendar-specific restrictions, discounts and cancellation terms require additional data.',
                     'Event-study intervals are pointwise. No HonestDiD or simultaneous bands are implemented.']}
    write_json(out / 'run_manifest.json', report)
    (out / 'README.txt').write_text('\n'.join(report['warnings']) + '\n', encoding='utf-8')
    if not quiet:
        print(json.dumps({'status': 'ANALYZED_CANONICAL_PANEL', 'kind': cfg['analysis_kind'],
                          'ids': len(ids), 'dates': dates, 'distinct_january_columns': distinct_policy_columns,
                          'output': str(out)}, ensure_ascii=False))
    return report


def selftest(out: Path):
    import numpy as np
    import pandas as pd
    make_output(out)
    dates = ['2024-03-15', '2024-06-15', '2024-09-15', '2024-12-15',
             '2025-03-15', '2025-06-15', '2025-09-15', '2025-12-15']
    cfg = {'analysis_kind': 'synthetic_test', 'pre_dates': dates[:4], 'post_dates': dates[4:],
           'reference_date': dates[3], 'primary_threshold': 28, 'thresholds': [28, 30, 31],
           'date_provenance': 'Synthetic fixture; these are NOT actual LA scrape dates.',
           'coverage_basis': 'Constructed complete synthetic grid.', 'treatment_basis': 'Artificial hex assignment.',
           'weight_basis': 'Artificial fixed positive unit weights; no model fitted.'}
    rows = []
    for g in range(40):
        treated = int(g >= 20)
        for k in range(20):
            for t, date in enumerate(dates):
                lo, hi, present = (2, 20, 1) if k < 6 else ((2, 90, 1) if k < 16 else (35, 90, 1))
                if k == 19:
                    lo = None
                if treated and t >= 4:
                    if k in [6, 7]: lo = 35
                    if k == 8: present, lo, hi = 0, None, None
                rows.append([f'synthetic_{g}_{k}', date, present, lo, hi, treated, f'hex_{g}', 1 + g % 3, 1])
    fixture = pd.DataFrame(rows, columns=REQUIRED)
    fixture.to_csv(out / 'synthetic_panel.csv', index=False)
    write_json(out / 'synthetic_design.json', cfg)
    r = analyze(out / 'synthetic_panel.csv', out / 'synthetic_design.json', out / 'synthetic_results', quiet=True)
    tests = []
    for k in [28, 30, 31]:
        expected = {'absent': .05, 'unknown_rule': 0, 'short_only': 0, 'flexible': -.15, 'long_only': .10}
        for s, expected_beta in expected.items():
            assert abs(r['coefficients_for_audit'][k][s] - expected_beta) < 1e-10
    tests.append('Known synthetic state DID coefficients recovered at all locked thresholds.')
    assert r['n_distinct_policy_columns'] == 1
    tests.append('Three January policy dates correctly detected as indistinguishable in quarterly fixture.')
    # Compare change-score coefficient with balanced weighted two-way demeaning.
    valid, locked_dates = validate_panel(fixture.copy(), cfg)
    ids = sorted(valid.listing_id.unique())
    unit = valid.drop_duplicates('listing_id').set_index('listing_id').loc[ids]
    a = valid.assign(y=(assign_states(valid, 28) == 'long_only').astype(float))
    y = a.pivot(index='listing_id', columns='snapshot_date', values='y').loc[ids, locked_dates].to_numpy()
    weights = unit.weight.to_numpy()
    x = unit.treated.to_numpy()[:, None] * np.array([0,0,0,0,1,1,1,1])[None, :]
    def within(z):
        return z-z.mean(axis=1, keepdims=True)-np.average(z, axis=0, weights=weights)[None, :]+np.average(z.mean(axis=1), weights=weights)
    xx, yy = within(x), within(y)
    b = (weights[:, None]*xx*yy).sum()/(weights[:, None]*xx*xx).sum()
    assert abs(b-.10) < 1e-10
    tests.append('Change-score DID agrees with balanced fixed-unit-weight two-way demeaning.')
    checks = [('duplicate_key', pd.concat([fixture, fixture.iloc[[0]]], ignore_index=True)),
              ('missing_riskset_row', fixture.iloc[1:].copy()),
              ('unverified_coverage', fixture.assign(coverage_ok=0)),
              ('time_varying_weight', fixture.assign(weight=np.where(np.arange(len(fixture))==0, 9, fixture.weight)))]
    for name, broken in checks:
        try:
            validate_panel(broken, cfg)
        except ValueError:
            tests.append('Fails closed on ' + name)
        else:
            raise AssertionError('Validation failed to reject: ' + name)
    # Verify covariance against an independently assembled cluster sandwich on deterministic noisy outcomes.
    rng = np.random.default_rng(20261013)
    Y = rng.normal(size=(len(ids), 3)) + .2*unit.treated.to_numpy()[:,None]
    bt, cv, G = group_wls(Y, unit.treated.to_numpy(), weights, unit.hex_id.to_numpy())
    try:
        import statsmodels.api as sm
        X = sm.add_constant(unit.treated.to_numpy())
        for j in range(3):
            fit = sm.WLS(Y[:,j], X, weights=weights).fit(cov_type='cluster', cov_kwds={'groups':unit.hex_id.to_numpy(), 'use_correction':True})
            assert abs(fit.params[1]-bt[j]) < 1e-10
            assert abs(fit.cov_params()[1,1]-cv[j,j]) < 1e-10
        tests.append('Cluster covariance agrees with statsmodels WLS benchmark on synthetic noisy outcomes.')
    except ImportError:
        tests.append('statsmodels covariance cross-check SKIPPED: optional dependency not installed.')
    result = {'status': 'SYNTHETIC_SOFTWARE_TESTS_ONLY', 'n_checks': len(tests), 'checks': tests,
              'real_LA_results_generated': False, 'note': 'Known artificial effects test implementation; not empirical evidence, power, or causal identification.'}
    write_json(out / 'selftest_report.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest='cmd', required=True)
    a = s.add_parser('audit'); a.add_argument('archive', type=Path); a.add_argument('--out', type=Path, required=True)
    a = s.add_parser('analyze'); a.add_argument('panel', type=Path); a.add_argument('--config', type=Path, required=True); a.add_argument('--out', type=Path, required=True)
    a = s.add_parser('selftest'); a.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.cmd == 'audit': audit_archive(args.archive, args.out)
        elif args.cmd == 'analyze': analyze(args.panel, args.config, args.out)
        else: selftest(args.out)
    except Exception as exc:
        print(f'FAILED_CLOSED: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
