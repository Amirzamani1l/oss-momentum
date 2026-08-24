# Methodology

## Sampling

The pipeline runs at 01:17, 09:43 and 17:29 UTC, skipping Fridays
(Asia/Tehran). Each run writes a single row per project keyed on
`(date, repo)`; the last run of a day overwrites the earlier two.

The series is therefore **daily**, not thrice-daily. Running more often
buys resilience against a failed run, not resolution.

## Metrics

### `stars_delta_{1,7,30}d`

Change in star count over the trailing window. The baseline is the newest
observation **at or before** `latest_date - N days`. If no such
observation exists — the dataset is younger than the window — the oldest
available row is used instead, so early numbers understate the true delta
rather than reporting nothing.

### `growth_30d_pct`

```
growth = (stars_delta_30d / (stars - stars_delta_30d)) * 100
```

Growth relative to the base at the start of the window. This is the
headline ranking metric because absolute star counts are dominated by
project age, not current traction.

Undefined (null) when the computed baseline is zero or negative.

### `momentum_z`

The z-score of `growth_30d_pct` across all tracked projects in the same
snapshot:

```
z = (growth - mean(growth)) / population_stddev(growth)
```

Population standard deviation (`ddof=0`), since the tracked set is the
entire population of interest, not a sample drawn from a larger one.

Guards: fewer than two non-null values yields null; zero variance yields
zero for every project rather than a division error.

A z above roughly +1.5 means a project is growing markedly faster than
its peers *this month*. It says nothing about absolute size.

### `issue_pressure`

```
pressure = (open_issues / stars) * 1000
```

Open issues per thousand stars — a rough proxy for maintenance load
normalised by project size. Flagged above 25.

This metric has a known bias: projects that use GitHub Issues as a
discussion forum score worse than projects that triage aggressively or
route support elsewhere. Read it as a prompt to look, not a verdict.

Note that GitHub's `open_issues_count` **includes open pull requests**.
The field is not corrected for this, because separating them costs an
extra API call per project per run.

### `pypi_cadence_days`

Median gap, in days, between the ten most recent PyPI releases. Requires
at least three releases with upload timestamps; yanked versions with no
files are skipped.

Median rather than mean, so a single multi-year gap in a project's early
history does not distort the current picture.

### `is_stale`

`days_since_push > 45`. Uses `pushed_at`, which reflects pushes to *any*
branch, so a project with active feature branches but a frozen default
branch will not be flagged.

## Known limitations

- **Stars are a weak proxy for adoption.** They measure attention, and
  attention is bursty: a conference talk or a front-page post produces a
  spike that has nothing to do with usage. Nothing here corrects for that.
- **No download data.** PyPI download counts are not available from the
  `pypi.org` JSON API; they require BigQuery or a third-party service.
  Release cadence stands in as a much weaker signal.
- **Survivorship bias.** The tracked set is 42 projects chosen for being
  well known. Projects that were once major and have since died are not
  in it, so category aggregates skew healthy.
- **Short history at first.** Thirty-day metrics are null or understated
  until the dataset is thirty days old. The report states its own coverage
  in the header for exactly this reason.
- **`open_issues_count` conflates issues and pull requests**, as noted
  above.

## Reproducibility

Raw API responses are archived under `data/snapshots/YYYY-MM-DD.json`.
The derived table can be rebuilt from them at any time; the analysis layer
is pure and deterministic given the same input.

## Findings

After each run, five conditions are evaluated against the latest snapshot.
Each produces a `Finding` with a stable key of the form `kind:owner/repo`.

| Kind | Condition | Severity |
| --- | --- | --- |
| `stalled` | `days_since_push > 45` | medium |
| `spike` | `momentum_z >= 2.5` | info |
| `slump` | `growth_30d_pct < 0` | medium |
| `drought` | `days_since_release > 180` **and** `pypi_cadence_days < 45` | medium |
| `unreachable` | 3 consecutive failed fetches | high |

`drought` deliberately requires both halves. A project that has always
released twice a year going quiet for six months is not news; a project
that shipped every fortnight and then stopped is.

`spike` is set at 2.5 standard deviations rather than 2.0 because star
growth has fat tails — a single popular post moves a project several
sigma without any change in adoption. The threshold is chosen to fire
rarely enough that each occurrence is worth reading.

### Reconciliation

Findings are diffed against currently open issues, not pushed as events:

| State | Action |
| --- | --- |
| Finding exists, no issue | Open one |
| Issue exists, finding cleared | Comment why, then close |
| Both exist | Do nothing |
| Issue has no radar marker | Ignore entirely |

The last row is the important one. Every generated issue embeds
`<!-- radar:kind:owner/repo -->` in its body, and only issues carrying
that marker are considered. Issues opened by a human are never read,
modified or closed.

Because the sync computes a desired state rather than reacting to changes,
running it repeatedly is a no-op. Three runs a day on an unchanged
ecosystem produce zero issue activity.

### Known limitations of the findings

- **`slump` is noisy.** GitHub periodically prunes spam accounts, which
  shows up as a genuine star loss across many projects at once. The issue
  body says so, but the condition cannot distinguish the two.
- **`stalled` uses `pushed_at`**, which covers every branch. A project
  with active feature branches and a frozen default branch will not fire.
- **`unreachable` cannot tell a rename from a deletion.** Both look like
  a 404. The issue asks a human to check.
