# inv-target-check

Check the targets exported in a Sphinx `objects.inv` against the actual built
documentation files **before publishing**. Find missing pages and missing HTML
anchors even when nothing in your own documentation links to those exports.

Python 3.11+, no runtime dependencies, no network access, no execution of `conf.py`.
[中文说明](README.zh-CN.md) · [MIT](LICENSE)

## Install and use

```sh
git clone https://github.com/KanadeK/inv-target-check.git
cd inv-target-check
python -m pip install .
inv-target-check docs/_build/html/objects.inv docs/_build/html --json
```

`python -m inv_target_check` is equivalent to the installed command.
Uninstall with `python -m pip uninstall inv-target-check`. No cache is created.

Run a complete demo without Sphinx:

```sh
python examples/make_demo.py demo-good
inv-target-check demo-good/objects.inv demo-good
python examples/make_demo.py demo-bad --broken
inv-target-check demo-bad/objects.inv demo-bad --json
```

The first audit returns 0; the second returns 1 with `missing-anchor`.
The generator refuses to overwrite an existing destination. Remove those two
generated directories when finished.

## What is checked

- Strict v2 header, bounded zlib decompression, UTF-8 records and malformed rows.
- Names containing spaces, roles containing extra colons, empty dirhtml root
  URIs and trailing `$` expansion to the object name.
- Files and directories (`index.html`), including exact filename case on Windows.
- Percent-encoded UTF-8 paths/anchors, HTML `id` attributes and legacy `<a name>`.
- Traversal, unsupported portable paths, and symlinks that escape the selected root.
- Every entry receives an outcome, including external targets that were not checked.

HTML anchors are case sensitive; the browser's special `top` fragment is accepted.
Queries do not change local file lookup. HTML attributes are parsed with the
standard-library HTML parser; no JavaScript is executed.

Relative targets are rooted at the supplied build directory. For root-relative
or absolute targets on your own site, declare the public directory it represents:

```sh
inv-target-check build/objects.inv build --base-url https://docs.example.com/project/ --json
```

`--base-url` ends in `/` and has no credentials, query or fragment. URLs under
that directory map to the local root. Other origins remain unverified. Targets
outside the mapped directory fail instead of reading adjacent files.

## Reports and exit codes

| Exit | Meaning |
|---|---|
| 0 | Every local target verified; any unverified external targets were explicitly allowed |
| 1 | Missing, unreadable or unsupported targets, or unverified external targets |
| 2 | Invalid inventory, root, base URL, or command usage; audit could not start |

`--allow-external` permits external entries without pretending they were checked.
Their `unverified` count remains in the report. This option never suppresses local
failures. JSON `schema_version: 1` includes project/version, summary and per-entry
source line, object name, role, original/expanded URI, mapped file and outcome.
Line numbers count the four textual header lines followed by decompressed rows.
The human report quotes input strings to keep terminal control characters inert.

## Why this tool?

[sphobjinv](https://github.com/bskinn/sphobjinv) is the established inventory
inspection/manipulation toolkit. [lychee](https://github.com/lycheeverse/lychee)
is a general link checker. This tool directly checks a compressed export inventory
against a release tree. It neither compares historical inventories nor crawls a site.
The failure mode is illustrated by
[google-cloud-python #15968](https://github.com/googleapis/google-cloud-python/issues/15968).

The parser follows the documented
[v2 inventory format](https://sphobjinv.readthedocs.io/en/latest/syntax.html);
directory mapping follows [Sphinx builders](https://www.sphinx-doc.org/en/master/usage/builders/index.html).
Implementation and example content are original; no Sphinx code is bundled.

## Limits

Only inventory v2 and UTF-8 HTML are supported. This is a filesystem audit, not a
deployment simulator: rewrites, MIME types, HTTP redirects, JavaScript-generated
anchors, custom HTML encodings and server-specific percent-encoded slash handling
are not modeled. Encoded path separators, Windows-special filename characters
and escaping symlinks fail explicitly. Files without fragments are existence checks.

A successful Sphinx build does not ensure its inventory is clean: optional module
indexes or singlehtml-only exports can name files/anchors that were never emitted.
Those are reported, not silently excluded. Decide whether your export or build
should change. Use `html`/`dirhtml` when publishing inventories for downstream users.

Limits: 16 MiB input inventory, 64 MiB expanded data, 250,000 rows, 16,384 characters
per row, 8 MiB per HTML file. At most 32 parsed anchor sets and 128 directory-name
sets are cached. Directories must be stable during the audit. The tool is read-only;
it does not repair an inventory or infer the correct replacement target.

## Development

```sh
python -m pip install -e . sphinx==9.2.0 ruff==0.17.2 build==1.6.1
python -m unittest discover -s tests -v
ruff check .
python -m build
```

The integration suite builds original fixtures with actual Sphinx `html`,
`dirhtml` and `singlehtml`, verifies real exports, and removes output pages to
confirm failures. Sphinx is a development-only dependency; that integration test
skips if unavailable. CI installs it, and runs on Python 3.11/3.13 on Linux and
Windows. Symlink creation tests skip on hosts without permission and run on Linux.
