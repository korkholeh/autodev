# Systematic debugging

Diagnose before you change. A patch that hides a symptom without a named root cause is not a fix.

1. **Reproduce.** Find the smallest reliable trigger: a failing test, one command, one request, one keystroke.
   If you cannot reproduce it, you cannot verify a fix.
2. **State expected vs actual** with real values, not adjectives.
3. **Localize.** Narrow to the smallest module. Use the top in-repo frame of the stack trace, not the library frame.
4. **Inspect real signals.** Logs, the debugger, a one-off script, the actual stored data, the actual HTTP exchange,
   the actual rendered tree. Do not reason from what the code "should" do.
5. **Form one testable hypothesis**: "X is null because the serializer drops it when Y" — something one observation
   can confirm or refute.
6. **Change one significant variable at a time** and re-test. Reverting a batch of guesses teaches nothing.
7. **Write a regression test that fails before the fix and passes after.** Test at the public boundary; mock only
   external I/O.
8. **Verify** with the narrowest sufficient checks (`verify-change.md`), including the step-1 reproduction.
9. **Fix the root cause.** If you must ship a mitigation instead, say so, name the underlying cause, and record a
   follow-up in `.autodev/DECISIONS.md`.

Never make a test pass by weakening it. Deleting, skipping, `xfail`-ing, loosening an assertion, or asserting the
buggy value are all the same failure: the suite now certifies the bug.
