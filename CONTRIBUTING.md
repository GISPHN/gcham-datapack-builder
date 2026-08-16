# Contributing

Contributions and reproducible bug reports are welcome.

## Bug reports

Please use the GitHub bug-report template and include:

- QGIS version
- operating system
- prefecture and municipality selection
- whether cached downloads were reused
- the complete error message and relevant lines from the plugin log
- steps required to reproduce the problem

Do not upload confidential or personal data. Source datasets used by this plugin are public government datasets and should normally be reproducible without attaching downloaded archives.

## Development

The plugin is written in Python/PyQGIS. QGIS 4.x is the primary target; compatibility code is retained for QGIS 3.44 LTR where practical.

Before submitting changes:

1. Run `python -m compileall` on the plugin Python files.
2. Run `python -m unittest discover -s tests -v`.
3. Confirm that the official plugin ZIP has exactly one top-level directory named `gcham_datapack_builder`.
4. Test installation from ZIP in a clean QGIS profile when possible.

## Pull requests

Keep changes focused, explain user-visible behavior, and update `CHANGELOG.md` when appropriate.
