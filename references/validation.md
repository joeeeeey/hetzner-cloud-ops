# Validation evidence

Validated 2026-10-08 against the implementation branch, using synthetic data.

- Python 3.10.14: **6 offline tests passed**, including functional and safety invariants.
- Standard skill frontmatter validator: passed. CLI `--help`: passed.
- skills CLI 1.7.1 under Node 22.22.0: installed in an isolated project for
  Codex, Claude Code and Cursor with telemetry disabled. All three discovered this skill.
  Codex/Cursor share `.agents/skills`; Claude Code uses a linked `.claude/skills` copy.
- Codex execution owner: ran the CLI and offline suite. Independent offline reviewer
  exercised synthetic provider responses and mutation previews.
- Claude Code native print-mode session: read the installed SKILL.md and ran this
  skill's suite with an explicit Python 3.10 interpreter and cleared provider environment.
  Five credential-free preview workflows across the suite also passed.
- Cursor Agent native execution: attempted, but stopped at sign-in. No native Cursor
  conversation or UI E2E is claimed. Installer discovery and shared CLI execution are verified.
- Animated SVG: Chromium render visually inspected as a full eight-product contact sheet;
  reduced-motion rendering also generated. No JavaScript or external assets in the SVG.
- No live provider authentication, production mutation, purchase or customer data tested.

These levels are distinct: installer discovery and offline tests do not establish live
account or native UI behavior. Provider schema changes and permissions still need validation
against a user's explicitly selected account.
