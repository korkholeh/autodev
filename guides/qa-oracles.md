# Oracles and test plans

## An oracle is the answer to "what is correct?"

A test asserts something is true. The oracle is *where that expectation came from*. There are two sources and only
one of them is worth anything:

- **From intent** — the spec, the acceptance criteria, the ADR, what the API documents about itself, what the screen
  tells the user it will do, what the operation *means*. This is an oracle.
- **From current behaviour** — running the code, seeing what happens, writing that down. This is not an oracle.
  It is a photograph.

A test written from a photograph passes today and keeps passing over every bug the product already has. Worse, once
it exists, fixing the bug turns it red and the cheap move is to "fix the test".

**Read the code to learn what exists and what to drive. Never to decide what the right answer is.**

If intent is genuinely undecided, do not pin today's behaviour. Record the case under `deferred_not_authored` with
the reason, and log it in `.autodev/DECISIONS.md` as an open product question.

## The plan file

One YAML file per feature, `e2e/plans/<feature>.plan.yaml`, written **before** the spec code. It is short, and it is
the artefact a human can argue with — much easier to review than a file of selectors.

```yaml
feature: password-change
surfaces: [app]                      # which runnable surfaces these cases drive
entry: "Settings → Security → Account password"   # where a person finds this by hand

under_test:                          # the code this feature is made of; a map for the next reader
  - src/auth/password.py::change_password
  - ui/settings/PasswordForm.tsx

oracle: >
  One paragraph: what should happen, and where that expectation came from — quote the spec line, the
  acceptance criterion, or the message the UI itself promises. Include what the operation means even when
  nobody wrote it down: after a password change, the new password signs you in and the old one does not.

scope_notes: >
  Setup decisions a reader needs: which persona, which seeded data, what is asserted and what is not.

cases:
  - id: happy-path
    priority: high
    steps: ["open the form", "enter the current password and a valid new one twice", "submit"]
    expected: "'Password change successful.' is shown and the form collapses"

  - id: wrong-current-password
    priority: high
    steps: ["open the form", "enter a wrong current password", "submit"]
    expected: "'Current password is incorrect.' on the field, no success message, password unchanged"
    oracle_note: "Confirmed against spec §4.2."

findings:                            # true, reported, deliberately not asserted
  - id: badge-stale-until-reload
    detail: >
      The "Updated" timestamp does not refresh until the page is reloaded. The documented side effect does
      happen, so there is nothing to fail, but the user is shown something false. Needs a product decision.

deferred_not_authored:               # branches not tested, each with a concrete reason
  - id: sms-second-factor
    reason: "calls a live SMS provider; no local stub or sandbox number available"
```

## Priorities

| Priority | Use it for |
|---|---|
| `high` | The feature is broken for real users if this fails |
| `medium` | A real defect with a workaround or a narrow blast radius |
| `low` | Polish, input handling, cosmetics |

A failing row is read with one question: *does this being red matter?* The priority is the plan's answer.

## Linking a plan to a spec

Every spec's docstring/comment opens with a tag:

```
[qa:password-change:happy-path]  The password changes and the card says so.
```

`[qa:<feature>:<case-id>]` — the feature is the plan file's name, the case is an `id:` inside it. That one string
lets the report say which case a test implements, how much it matters, and where the oracle is written down.
If the tag names a case the plan no longer has, the spec and the plan have drifted — fix one of them.

## Never skip silently

A test that does not exist and a test that passes look identical from the outside. The only difference is whether
anyone knows. `deferred_not_authored` is that difference: every branch you chose not to cover, with its reason.
