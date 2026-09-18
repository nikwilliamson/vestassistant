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

- **Register the brand with `home-assistant/brands`.** The HACS check is
  satisfied by the copies now shipped in
  `custom_components/vestassistant/brand/`, but only the brands repo makes the
  icon appear in Home Assistant's own UI. The assets are ready: `brand/` holds
  `icon.png` at 256x256 and `icon@2x.png` at 512x512, trimmed and squared, which
  is exactly what the PR wants. There is no `logo.png` on purpose - the logo
  would be the same artwork as the icon, and brands says to submit only the
  icons in that case. `brand/source.png` is the full-resolution original the
  two are generated from.
Resolved: the dead `abort.reconfigure_successful` string has been dropped.

## Quality scale

Target is bronze for 0.1, silver once reauth and offline recovery are proven
against a real board, gold when discovery and diagnostics land.

Bronze blockers:

- `config-flow-test-coverage`
- `test-coverage`
- `brands` — assets are ready in `brand/`; needs the PR to home-assistant/brands

Resolved: `docs-removal-instructions` — see "Removing it" in the README.

Silver:

- `entity-unavailable` — entities should go unavailable when the board can't
  be reached, rather than holding the last known grid
- `parallel-updates`

Resolved: `docs-troubleshooting` — see "Troubleshooting" in the README.

Gold and beyond: `discovery`, `diagnostics`, `reconfiguration-flow`,
`repair-issues`, `strict-typing`.

## Verification gaps

- The scheduler and layout tests only run in CI (`pip install pytest vesta
  ruff`). There's no local dev environment, so changes land unverified until
  the push.
- The write-outcome and thread-safety fixes in 0.1.1 have no test coverage —
  both were found by running against a real board, not by the suite.
