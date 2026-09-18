# Backlog

Things worth doing, roughly in the order they start to hurt.

## Release plumbing

Resolved in 0.1.2: the release workflow is gone. It stamped `manifest.json`
inside the CI checkout without committing the result, and `hacs.json` sets no
`zip_release`, so HACS installed from the tag and the stamp did nothing. It
also could not have attached its zip anyway - the job had no
`permissions: contents: write` and failed on `action-gh-release` with
"Resource not accessible by integration". Releases are manual now, which is
what the process already was in practice. See "Releasing" in the README.

Still open:

- **Register the brand with `home-assistant/brands`.** The last HACS check
  still failing. Assets are in `brand/`. Alternatively HACS accepts them at
  `custom_components/vestassistant/brand/icon.png`, but the brands repo is the
  route that also makes the icon show up in Home Assistant itself.
- **`abort.reconfigure_successful` in `config_subentries.source` is dead.**
  `SourceSubentryFlow` has no reconfigure step, so nothing can emit it. Either
  add the step or drop the string.

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
