# Backlog

Things worth doing, roughly in the order they start to hurt.

## Release plumbing

- **Delete the manifest-stamping step from `.github/workflows/release.yaml`.**
  It rewrites `manifest.json` inside the CI checkout and never commits the
  result, and `hacs.json` sets no `zip_release`, so HACS installs from the tag
  rather than from the attached zip. The stamp is decorative: the tag still
  carries whatever version was committed. Bumping `manifest.json` by hand in
  the same commit as the tag is the reliable path, and it's what the step
  pretends to automate.
- **Decide whether to use `zip_release` at all.** If the zip becomes the
  install source, stamping in CI starts working and the manual bump goes away.
  If not, drop the zip asset too and keep the release plain. Right now it's
  half of each.

## Quality scale

Target is bronze for 0.1, silver once reauth and offline recovery are proven
against a real board, gold when discovery and diagnostics land.

Bronze blockers:

- `config-flow-test-coverage`
- `test-coverage`
- `brands` — needs a PR to home-assistant/brands (icon and logo are in `brand/`)
- `docs-removal-instructions`

Silver:

- `entity-unavailable` — entities should go unavailable when the board can't
  be reached, rather than holding the last known grid
- `parallel-updates`
- `docs-troubleshooting`

Gold and beyond: `discovery`, `diagnostics`, `reconfiguration-flow`,
`repair-issues`, `strict-typing`.

## Verification gaps

- The scheduler and layout tests only run in CI (`pip install pytest vesta
  ruff`). There's no local dev environment, so changes land unverified until
  the push.
- The write-outcome and thread-safety fixes in 0.1.1 have no test coverage —
  both were found by running against a real board, not by the suite.
