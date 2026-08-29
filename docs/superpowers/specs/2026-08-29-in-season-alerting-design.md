# In-Season Alerting and Dashboard — Design

**Date:** 2026-08-29
**Status:** Approved for planning
**Supersedes:** the notification and phasing sections of
`2026-08-20-fantasy-football-co-coach-design.md`, which remain accurate for the
draft board and data layer.

## Problem

The user does not forget *how* to manage a fantasy team. He forgets *when*. A
starter on bye, a Sunday-morning inactive, a bench player clearly outscoring a
starter — each is obvious once seen and worthless once the game has kicked off.

The product's job is therefore narrow and unglamorous: **interrupt him, in time,
with a decision already made.** Everything else is secondary.

The draft is explicitly out of scope. He drafts elsewhere. This system manages
the team across the season.

## What exists today

Built and working: the ESPN league adapter (rosters, records, settings),
a draft board, a player-identity crosswalk giving every player ESPN/MFL/nflverse
ids, a SQLite cache with stale-fallback, and two web pages.

Not built at all: **anything that notifies.** No `notify/`, no scheduler, no
projections source, no lineup advisor, no `model/scoring.py`. The single most
important capability is the one with no code behind it.

## Non-goals

- **Automated lineup changes.** ESPN publishes no write API. Reverse-engineering
  one and submitting changes on the user's behalf risks his account for a
  saving of two taps. The tool tells him what to do; he does it.
- Draft assistance. Handled elsewhere.
- Waiver-wire recommendations. Deferred to a later phase so lineup integrity
  ships first and gets proven across real weeks.
- Multi-user support, hosting, login.

## Constraints

- **Runs on a dedicated iMac** the user leaves on. This machine sleeps, which
  is the single largest operational risk (see Scheduling).
- **Free data only.** No paid projection feeds.
- **Projections come from ESPN and are mediocre.** Every design decision that
  touches a projected number assumes it carries real error.
- iPhone for notifications. Channel undecided by design (see Channels).

## Architecture

```
launchd (per-window)
   │
   ▼
advisors/lineup.py ──► findings[] ──┬──► notify/  (interrupt tier)
   ▲                                └──► web/data/week.json ──► web/week.html
   │
leagues/espn.py (rosters, projections, injury status)
sources/nflverse.py (NFL schedule → per-player kickoff times)
```

**One finding set drives both the alert and the page.** The dashboard is the
notification content rendered large. This is not merely tidy: it guarantees the
page can never disagree with the text message, which is the failure that would
destroy trust in both.

Findings stay structured — `{kind, player, slot, replacement, delta, locks_at,
reason}` — never prose. Deterministic Python decides *what is true*; wording is
applied at the edge.

## The alert model

### Two tiers

The user asked for "ideally just 1" alert. The resolution is not a noise dial but
two channels with different jobs:

| Tier | Channel | Fires when | Typical frequency |
|---|---|---|---|
| **Interrupt** | push / SMS | A starter cannot score **and** the slot is still changeable | Often zero per week |
| **Digest** | email | Everything else — upgrades, injuries, banter, standings | Twice weekly, fixed |

Zero interrupts in a clean week is the system working, not the system broken.
Only the interrupt tier is allowed to buzz the phone, and only three kinds
qualify:

1. **Starter on bye** — certain, detected days ahead.
2. **Starter ruled OUT / IR** — certain.
3. **Starter downgraded to OUT close to kickoff** — the inactives sweep below.

**Bench-over-starter upgrades never interrupt by default.** They rest on
projections carrying several points of error; a 0.4-point "edge" is noise, and
alerts the user learns to ignore are worse than no alerts. They ride the digest,
and are individually promotable to interrupt via config with a points threshold.

### The inactives sweep

The highest-value check in the system, and the least obvious. Bye weeks are
visible for months; what actually costs points is a **Questionable starter
declared inactive 75–90 minutes before kickoff** while the user is at brunch.

Roughly 90 minutes before each *distinct* kickoff time on the roster, re-fetch
status for that window's Questionable starters only, and alert on newly-OUT.
Small, targeted, and the closest thing here to a genuine edge.

### Alert shape

Batched per lock window, with reasons. Every problem sharing a kickoff arrives
as one message carrying each fix and the combined swing:

```
2 lineup problems, lock 1:00PM:
- Godwin OUT → Pittman +11.4
- McBride BYE → Ferguson +8.1
Both = +19.5, flips you to a win.
```

Under 160 characters, deliberately. SMS splits past that and carrier
email-to-SMS gateways routinely mangle or drop the tail, so the message must fit
one segment. Push channels have no such ceiling; the SMS renderer is the
constrained one and sets the budget.

### Quiet hours

**23:00–08:00 America/New_York.** Anything discovered inside the window queues
and delivers at 08:00. Nothing is dropped, nothing wakes him. The digest is
never urgent and is only ever sent inside waking hours.

## Scheduling

**`launchd`, not `cron`.** This is a correctness requirement, not a preference:
cron does not run missed jobs on a sleeping Mac, so a `cron`-based build would
appear to work and silently fail on exactly the Sunday mornings that matter.
`launchd`'s `StartCalendarInterval` runs on wake, and `pmset repeat wake` can
wake the machine ahead of each window.

Checks are timed off **each player's actual kickoff**, not a single weekly sweep.
NFL weeks lock in five separate windows (Thu night, Sun 1pm, Sun 4pm, Sun night,
Mon night); one "24 hours before the week" alarm would fire uselessly for some
players and far too late for others. Kickoff times come from the free nflverse
schedule.

| Job | When | Purpose |
|---|---|---|
| Lineup check | ~24h and ~3h before each lock window | Byes, OUT, IR |
| Inactives sweep | ~90m before each kickoff | Newly-OUT Questionable starters |
| Weekly digest | Tuesday morning | Results, banter, upgrades, injury notes |
| Heartbeat | Hourly | Dead-man's switch |

### The dead-man's switch

If ESPN cookies expire or the network fails, the user receives **no alert** —
indistinguishable from "nothing is wrong." That silent-failure mode would
quietly negate the entire system.

A heartbeat records each successful check. If none has succeeded in 12 hours
during the season, an alert fires saying so. `EspnAuthError` (already
implemented, raised distinctly on 401/403 and deliberately not masked by stale
cache) is its most likely trigger.

## Channels

The user does not yet know which channel he will actually read, and guessing
would be wasted work. All three ship behind one `Notifier` interface:

- **Email** — SMTP. Carries the digest. Free, no ceiling.
- **Email-to-SMS gateway** — free texting; needs his carrier; 160-char budget.
- **ntfy.sh** — free iPhone push; needs the app; no length ceiling.

Plus `ffcoach notify --test <channel>` to send a sample through each, and
`--dry-run` to print what *would* be sent without sending. He picks empirically
in five minutes rather than theorizing. **Pushover ($5, supports iOS Critical
Alerts that bypass Do Not Disturb) stays an escape hatch** if free push proves
unreliable — the interface makes adding it a single file.

Per-alert-type routing lives in config:

```yaml
notifications:
  channels:
    push: ntfy
    email: <address>
  quiet_hours: {start: "23:00", end: "08:00", tz: America/New_York}
  alerts:
    starter_bye:      {enabled: true,  tier: interrupt}
    starter_out:      {enabled: true,  tier: interrupt}
    inactive_late:    {enabled: true,  tier: interrupt}
    bench_upgrade:    {enabled: true,  tier: digest, min_delta: 3.0}
    smack_talk:       {enabled: true,  tier: digest}
    espn_auth:        {enabled: true,  tier: interrupt}
    heartbeat_missed: {enabled: true,  tier: interrupt}
```

## The page

`web/week.html`, built UI-first with mock data and reviewed before any backend
is wired — the user's explicit sequencing.

**Action Queue is the body; the matchup is a persistent header strip.** The
strip carries the score and a bar; the body carries the fixes. The matchup
provides motivation without competing for space, and each fix is framed as its
swing ("fix 2 slots → +13.6, and you win"), which is the strongest idea from the
matchup-first layout carried into an action-first page.

Each action card shows the change, the reasoning, and a **collapsed** "how to do
this on ESPN" block the user expands only when he wants it.

The **clean-week state is a first-class design**, not an afterthought: most
weeks nothing is broken, and a page showing only a green check gives no reason
to open it. The always-visible score, the next scheduled check, and the
opponent's visible weaknesses carry that state.

Projected scores render **rounded with the source named** — "You 119 – Dave 124
(ESPN proj)". Decimals imply a precision ESPN's projections do not have.

Existing UX rules carry over unchanged: real terminology never renamed,
explain-mode annotates only, every recommendation states its reason inline, no
dollar figures.

## Smack talk

Delivered in the Tuesday digest as **written, copy-paste-ready lines**.

The split matters: `advisors/smack.py` finds *facts* deterministically — bench
points left behind, loss margins, repeat bye-week starts, blowouts, lowest
weekly score — and those facts are always true. Only the wording is generated.

Findings target **decisions and outcomes, never people**. "Benching a 26-point
back is a choice" roasts the move; anything about the person does not ship.
Funnier, and it survives being screenshotted.

## Error handling

- A failed source serves stale cache and marks the payload stale, as today.
- ESPN auth failure raises `EspnAuthError`, never masked by stale cache, and
  routes to the interrupt tier.
- A lineup slot that cannot be evaluated (missing projection, unmatched player)
  is **reported as unknown rather than assumed fine**. Silence must never be
  manufactured from missing data — that is the exact failure the product exists
  to prevent.
- Every alert is recorded, so duplicates are suppressed and history is
  inspectable.

## Testing

- `advisors/lineup.py` — pure functions over fixture rosters. Bye, OUT, IR,
  upgrade-above-threshold, upgrade-below-threshold, and already-locked slots are
  each a case.
- Lock-window arithmetic and quiet-hours deferral get an injected clock, as
  `Cache` already does. No test sleeps or depends on wall time.
- `notify/` — a fake notifier asserts message content, that SMS renders under
  160 characters, that nothing sends inside quiet hours, and that a clean week
  sends nothing at all.
- Browser logic follows the existing rule: if it computes it lives in a
  `*_render.js` with tests; if it touches the DOM it stays trivial.

## Phasing

| Phase | Delivers | Gate |
|---|---|---|
| **A** | `week.html` with mock data, full design review | User approves the look |
| **B** | `advisors/lineup.py` + ESPN projections; page runs on real data | ESPN cookies present |
| **C** | `notify/` + channel bake-off via `--test`; interrupt tier live | Channel chosen |
| **D** | `launchd` scheduling, inactives sweep, heartbeat | Runs unattended |
| **E** | Tuesday digest + smack talk | — |
| **F** | Waiver wire | Deferred |

Phase A ships no functionality by design. The user reviews the interface before
any plumbing is built, so layout disagreements cost mockup edits rather than
rework.

## Open questions

- **Carrier**, if the email-to-SMS channel wins the bake-off.
- **League scoring rules.** Still placeholder defaults. ESPN's `mSettings` view
  is already fetched and may populate them automatically; custom scoring would
  require `model/scoring.py`, still unbuilt.
- **Projection quality is unmeasured.** Worth logging projected-vs-actual all
  season so the `min_delta` threshold can eventually be set from evidence rather
  than a guess.
