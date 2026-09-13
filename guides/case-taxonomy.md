# Case taxonomy

The code tells you which cases are *reachable*. It does not volunteer the cases below — enumerate them yourself,
then keep the ones that are real for this feature and record the rest as `deferred_not_authored` with a reason.

**Happy path** — the main task, completed the way the spec describes it. At least one per feature, always `high`.

**Input and boundaries** — empty, whitespace-only, maximum length, over maximum, zero, negative, very large,
wrong type, wrong format, leading/trailing spaces, unicode and emoji, locale decimal separators, dates around
midnight and across a timezone or DST boundary, currency rounding.

**State** — empty state (nothing created yet), single item, many items (does it paginate, scroll, truncate?),
loading, stale, and the state after a failure.

**Errors** — the operation fails for a reason the user can act on, and the app says which reason. A wrong
credential, a rejected payment, a file that will not parse, a name already taken. Assert the message, not a blank screen.

**Permissions and identity** — every role the spec names, including the one that must be refused. Pair every refusal
case with a positive case on the same surface: a test that only proves "staff cannot see this" would also pass if the
screen were broken for everyone. Refusal must be visible and explained, not a blank page or a silent redirect.

**Idempotency and repetition** — double submit, double click, a retried request, the same file uploaded twice,
re-running the same command. Nothing should be created twice or charged twice.

**Navigation and lifecycle** — back, forward, refresh, deep link into the middle of a flow, cancel halfway,
resume, close and reopen, restart the app, session or token expiry.

**Asynchronous chains** — an action whose result arrives later (a job, a webhook, a background import). Assert the
end state a user can observe, and wait for the observable signal rather than sleeping a fixed interval.

**Persistence** — the change survives a reload, a restart, and a second device or session where that applies.

**Concurrency** — two actors touching the same record, where the spec makes it possible.

**Accessibility and input modes** — keyboard-only path through the flow, focus order, and screen-reader labels on
the controls the flow needs, where the product commits to them.

**Platform sanity** — narrow window / small screen, dark mode, the smallest supported OS version, offline.

## Sizing

Most features need 4–12 cases. Prefer a small number of cases that each prove something the spec claims over a wide
grid of variations that prove the same branch repeatedly.
