# Context-efficient work

Read to find the edit boundary, then stop. More context is not more correct.

1. Start from the step's own inputs: the plan, the spec section it names, `git status`, `CLAUDE.md`,
   `.autodev/ARCHITECTURE.md`, `.autodev/PROFILE.md`. Open the nearest relevant directory, not the whole tree.
2. Search for symbols and the nearest similar implementation (grep a type, function, route, or component name)
   before reading any file top to bottom.
3. Read line ranges, not whole large files. Widen only when the range is not enough.
4. Never recursively scan generated or vendored trees: `node_modules/`, `.venv/`, `target/`, `build/`, `dist/`,
   `.build/`, `DerivedData/`, `__pycache__/`, `.next/`, lockfiles, snapshots, test fixtures data.
5. Read the public contract before the implementation: the signature, the schema, the route table, the protocol —
   then the body only if you must change it.
6. Stop collecting once you can name the files to edit and the checks to run. Then start.
7. Trust what you already read in this session. Do not reopen an unchanged file without a new reason.
8. `.autodev/DECISIONS.md` is a whole run's log, newest last, one `## ` section per step. Read the slice your step
   names, and grep the rest by topic — never read it top to bottom.
9. Prefer the project's own docs (`CLAUDE.md`, `docs/dev/`, `.autodev/`) over re-deriving documented structure from source.
10. Reach for external library docs only for unfamiliar or version-sensitive APIs — and check the pinned version first
   (lockfile, `Cargo.toml`, `package.json`, `Package.resolved`, `requirements*.txt`, `pyproject.toml`).
11. Ask for one symbol or topic, not a library's whole documentation set.
