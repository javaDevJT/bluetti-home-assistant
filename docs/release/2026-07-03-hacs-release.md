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
- Release tag: `v1.1.0`
- Integration domain: `bluetti`
- Integration version: `1.1.0`

No zip-release artifact is required because the repository uses the standard
`custom_components/bluetti` layout. HACS can use the GitHub release source
archive.
