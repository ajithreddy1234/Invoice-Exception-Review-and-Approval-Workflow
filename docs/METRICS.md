# What the dashboard and stage timings measure

All metrics use the database and the same enabled actor/ownership scope as history.
Vendor and currency filters apply. Unknown-currency records remain included in
counts and timing for the selected currency, as in the existing review-count model;
no unknown currency is converted into a monetary amount.

## Outcome mix

Current submission states are grouped as accepted, review (needs_review plus
reference_hold), blocked duplicate, rejected, technical failure, expired and
processing (received plus processing). Each invoice contributes once to its
current outcome. Retrying a run does not create another invoice outcome.

## Straight-through acceptance

Numerator: accepted invoices with method=automatic, no review_actions and no
processing.retry_requested audit event. The initial upload is not a manual review;
an application-owned provider retry is not a user-requested rerun.

Denominator: submissions whose current state is not received/processing. It
includes review holds, blocked duplicates, rejections, technical failures and
expiry. This is acceptance without intervention, not an assertion that every
automatic block/review routing is a completed human-free business process.
Empty denominators show no outcomes, not 100%.

## Median processing time

Use each scoped invoice's latest completed automated processing run, excluding
admin_revalidated runs and rows without valid start/finish timestamps. Duration is
finished_at minus started_at: provider waits and lease recovery are included;
queue time, admin review and publication are excluded. Failed/in-progress runs
are excluded from the timing sample, and sample count is displayed.

Postgres computes exact medians for all-vendor/currency and vendor/currency groups.
The frontend selects the proper aggregate; it never averages vendor medians or
estimates from the latest 200 activity records. Aggregates, not unbounded timing
samples, are returned to the client.

## Per-run stage view

Queue wait uses saved created_at/started_at. Each processing.stage audit event
starts a recorded stage; the next saved stage or run finish ends it. Repeated
retry/recovery stages remain separate. The view is scoped to the latest run and
does not mix earlier attempts. An active stage has no fabricated end/duration.
Absent or inconsistent timestamps show Not recorded. These are application-event
intervals, not a profiler's CPU/network breakdown or proof of hosted capacity.
