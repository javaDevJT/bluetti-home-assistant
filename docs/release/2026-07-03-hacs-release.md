# 2026-07-03 HACS Release Notes

## HACS Requirements Checked

Official HACS publishing documentation was checked before creating the public
fork/release.

- Integration repositories should use the `custom_components/<domain>/...`
  structure.
- A root `hacs.json` is required for HACS UI metadata.
- `manifest.json` must include at least `domain`, `documentation`,
  `issue_tracker`, `codeowners`, `name`, and `version`.
- GitHub releases are optional for HACS, but publishing releases lets HACS offer
  tagged versions instead of only the default branch.

## Release Shape

- Repository: `https://github.com/javaDevJT/bluetti-home-assistant`
- HACS type: Integration
- Latest release tag: `v1.1.4`
- Integration domain: `bluetti`
- Integration version: `1.1.4`

No zip-release artifact is required because the repository uses the standard
`custom_components/bluetti` layout. HACS can use the GitHub release source
archive.

## v1.1.1 Patch

The initial `v1.1.0` Hub A1 setup path treated an empty/non-OK
`deviceRemoteSearch` response as fatal before trying the read-only telemetry
endpoints. `v1.1.1` keeps `deviceRemoteSearch` as the preferred identity source
but falls back to Hub A1 telemetry when that lookup does not return device data.

The patch also preserves BLUETTI response `code` and `message` fields and logs
a redacted response summary for Hub A1 setup failures instead of only
`RuntimeError`.

## v1.1.2 Patch

The `v1.1.1` path could still show zero readings for Apex-family devices when
the standard Home Assistant `/deviceStates` response returned stale zeros.
`v1.1.2` overlays app-side `lastAlive` values onto existing Apex entities and
prefers realtime/lastAlive values over Hub A1 top-level zero placeholders.

## v1.1.3 Patch

The `v1.1.2` overlay still ran after Home Assistant entities could be created
from cached zero-valued config-entry product data. `v1.1.3` refreshes selected
Hub A1 and Apex-family products from read-only app telemetry before entity setup
so startup state no longer depends on a later background refresh.

## v1.1.4 Patch

The `v1.1.3` change still allowed Home Assistant entities to be forwarded
before each runtime `BluettiDevice` completed a read-only update. `v1.1.4`
awaits one initial device refresh before entity setup, persists refreshed
selected product snapshots, and logs serial-safe value summaries at startup to
show whether product/runtime state is zero or nonzero before entities are
created.
