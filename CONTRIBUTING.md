# Contributing

## Running the tests

The scheduler, layout, fitting and chip logic are deliberately free of Home
Assistant imports, so the parts that are easy to get wrong can be tested
directly:

```bash
pip install pytest vesta ruff
pytest -q
ruff check custom_components tests
```

Both are what CI runs, alongside hassfest and HACS validation.

Anything under `custom_components/vestassistant/core/` must never import
`homeassistant` — that constraint is the whole reason the suite runs without a
harness. The Home Assistant-facing layer (the coordinator, config flow,
sources and services) has no automated coverage yet; see `BACKLOG.md`.

## Releasing

HACS compares the `version` in `manifest.json`, so bump it in the same commit
as the tag. Nothing stamps it for you.

```bash
# edit custom_components/vestassistant/manifest.json
git commit -am "Release 0.3.0"
git tag v0.3.0 && git push && git push --tags
gh release create v0.3.0 --title v0.3.0 --notes "..."
```

## Two things that have bitten before

**Braces in `strings.json` are ICU placeholders.** The frontend will try to
interpolate anything in `{...}` and throw `MISSING_VALUE` if nothing supplies
it, and hassfest rejects any that is not a valid identifier. Escape a literal
brace by quoting it: `'{n}'`.

**`strings.json` and `translations/en.json` must stay identical.** Edit them as
text rather than round-tripping through `json.dumps`, which reformats the whole
file and buries the real change.
