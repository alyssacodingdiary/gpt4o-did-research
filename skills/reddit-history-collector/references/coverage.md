# Coverage and historical DID

## Statuses

- api_exhausted: validated interval returned fewer than the limit. Conditional on the service honoring the documented contract, the available archive query is exhausted; this is not a Reddit census claim.
- split: full page or query timeout; narrower intervals are queued. Retain parent-page records without claiming complete coverage.
- saturated_second: even a one-second interval filled the limit. Tied timestamps cannot safely be resolved by advancing a time cursor; obtain an archive or leave unresolved.
- http_error/network_error/invalid_payload: unknown observation, not zero comments.
- server_busy: the service explicitly asks the client to slow down (including HTTP 422 capacity messages). Stop and retain the pending interval; do not retry by immediately subdividing it.
- pending: request budget, interruption or access stop left a cell unresolved.
- archive_file_exhausted: the supplied file was fully read. It may itself be a sample or incomplete archive.

API requests overlap the lower boundary by one second and normalized records are filtered to [start,end). Saturation uses the unfiltered page. Boundary clutter can therefore conservatively prevent exhaustion. IDs deduplicate overlap. Divergent payload versions are counted, with the first observed version retained.

## A frame usable for DID

Freeze an independently verified event/exposure date, pre/post windows, communities and comparison definitions before outcome inspection. Keep the activity frame independent of sentiment or topic labels. Audit community × date × record-type coverage and source vintage. Build baseline cohorts from pre-event observations.

Separate observed community entry, sample absence, switching expression and verified product use. Post-event return selection can bias the primary analysis. A first-entry risk set with mechanically zero previous entries is not an ordinary DID outcome.

If sampling text, use a probability design on a known eligible frame and retain cell denominators, inclusion probabilities and seed. Monthly first-N, high-score comments and unknown balanced quotas cannot estimate total volume or inactivity.

Agency requires validated measures and competing explanations (competence, choice loss, cost, task changes, verification). Fewer complaints do not demonstrate less agency. Data collection cannot repair an invalid counterfactual or isolate tone from simultaneous product changes.

## Reproduction

Preserve plans, source bytes/hashes, dependency versions, logs and audit outputs. Replaying an API run with the same private key must reconstruct identical normalized records from saved responses without network access. Re-convert archives from identical files/configuration/key. A new live snapshot is not a test of offline reproducibility.
