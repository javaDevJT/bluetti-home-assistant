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
- Latest release tag: `v1.1.14`
- Integration domain: `bluetti`
- Integration version: `1.1.14`

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

## v1.1.5 Patch

The `v1.1.4` startup summaries showed Hub A1 and Apex-family values were already
zero-heavy before Home Assistant entity creation. `v1.1.5` adds serial-safe
endpoint summaries for app direct lookup, home-device fallback, Hub A1 optional
telemetry endpoints, and the final synthetic Hub A1 state list so the next live
run can identify whether BLUETTI is returning zero payloads or the integration
is selecting the wrong payload branch.

## v1.1.6 Patch

The `v1.1.5` diagnostics showed direct app lookup can return broad device
records without nested `lastAlive`, while app `homeDevices` can contain the
richer telemetry needed for Apex-family readings. `v1.1.6` prefers a matching
`homeDevices` row when it has better telemetry and lets HA1 fall back to an
Apex-family app telemetry row when Hub-specific endpoints return only online or
null values.

## v1.1.7 Patch

The `v1.1.6` fallback could populate HA1 values but leave them static because
runtime updates still depended on websocket events. `v1.1.7` registers a
60-second Home Assistant interval refresh for selected devices and cancels it
on unload/remove, so HA1/Apex fallback telemetry is re-read after startup.

## v1.1.8 Patch

The `v1.1.7` refresh path showed related Apex-family fallback telemetry can
still be stale and can expose battery values that should not be labeled as HA1
SOC/SOH/voltage. `v1.1.8` ignores stale related fallback rows, keeps related
fallback limited to power/switch fields, omits related fallback battery fields
from HA1, and logs successful periodic runtime summaries for refresh proof.

## v1.1.9 Patch

The `v1.1.8` runtime summaries proved the periodic refresh loop is firing, but
matching Apex-family `homeDevices.lastAlive` rows could still override live
direct device state with stale static app snapshots. `v1.1.9` applies the same
freshness gate to Apex-family app override selection so stale app snapshots do
not replace the refreshed Home Assistant device state.

## v1.1.10 Patch

The `v1.1.9` runtime summaries showed fresh app-side system telemetry arriving
from the `FP` row every refresh cycle while the `EL100V2` row only exposed pack
SOH/voltage/energy details and HA1-specific endpoints still returned online
only. `v1.1.10` treats fresh `FP`/Apex system telemetry as the preferred Hub A1
related fallback source and only permits battery SOC/SOH/voltage through that
system-source path, preserving the guard against stale EL100V2 pack values.

## v1.1.11 Patch

The `v1.1.10` model gate was too broad: in the live account, `FP` is
FridgePower, not verified Hub A1 or Apex system telemetry. `v1.1.11` removes
`FP` from the Hub A1 related-source gate so HA1 no longer copies FridgePower SOC
or power readings. The v1.1.9 stale snapshot guard remains in place.

## v1.1.12 Patch

After removing the incorrect FridgePower fallback, HA1 returned to zero readings
because zero-valued optional realtime/lastAlive payloads masked the non-zero
direct HA1 `deviceRemoteSearch` fields captured earlier. `v1.1.12` keeps the
verified direct HA1 app lookup path and lets non-zero direct HA1 values win over
zero optional telemetry placeholders while preserving non-zero realtime priority.

## v1.1.13 Patch

The next Home Assistant log showed HA1 direct app lookup repeatedly returning
`The device does not exist`, while optional HA1 endpoints stayed null/zero and
non-HA1 app telemetry continued refreshing. `v1.1.13` adds serial-safe target
hash/length diagnostics to app direct lookup, HA1 optional telemetry, and app
home-device serial matching so the next runtime log can prove whether Home
Assistant is querying the same Hub A1 serial that succeeded in capture.

## v1.1.14 Patch

The `v1.1.13` diagnostics proved the runtime was querying `Hub` and `A1`
instead of a real Hub A1 serial because the friendly name `Hub A1` had been
entered in the serial field and split on whitespace. `v1.1.14` rejects
friendly-name/model fragments as Hub A1 serials and removes cached synthetic
HA1 products with invalid short `sn` values during setup.
