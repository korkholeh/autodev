# User documentation

Written for the person using the product, who does not know its internals and does not care about them.
Complete sentences, complete steps, no jargon from the codebase.

## Where it lives

```
docs/user/
  README.md            index: what this product does, who it is for, where to start
  getting-started.md   install/launch, then the first successful task, end to end
  <feature>.md         one page per feature the user can name
  faq.md               real questions, with answers
  troubleshooting.md   "it did not work" → what to check, in order
```

For a GUI or TUI app, also record the keyboard shortcuts and every destructive action with its confirmation.

## Rules

1. **Task-shaped, not feature-shaped.** A page is "Export a report", not "The Export module".
2. **Start from what the user sees.** Name the actual button, menu item, key, flag, or URL — exactly as it appears
   on screen. If you are unsure of the label, read the UI code or run the app; never guess a label.
3. **Numbered steps for anything with more than one action.** One action per step, and the observable result of it.
4. **State the outcome.** After the last step, say what the user should now see. That is how they know it worked.
5. **Cover the failure the user will actually hit** — wrong input, missing permission, no network, empty state —
   with what to do about it.
6. **No internal vocabulary.** No class names, no table names, no queue names, no "the serializer". If an internal
   concept leaks into the UI, document the UI's name for it.
7. **No promises the build does not keep.** Document only what exists in this version.
8. **Screens change.** Prefer stable labels and flows over pixel descriptions; do not invent screenshots.

## Per phase

Each phase that ships something a user can see updates the affected pages in the same step that ships it, and adds
a CHANGELOG entry in the user's language ("You can now export a report as CSV"), not the commit's.
