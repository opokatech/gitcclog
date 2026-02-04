# GIT Conventional Commits LOG

`gitcclog` stands for **Git Conventional Commits Log** and supports the
[v1.0.0 specification](https://www.conventionalcommits.org/en/v1.0.0/#specification).

The version numbers follow [semantic versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## Motivation

_Why yet another conventional-commits-thing? There are already dozens of them..._

The goal was to have a **very simple** tool with following features:

- is trivial to deploy (just copy **one** file, no need to _install it_ system-wide or in virtual environment),
- has no external dependencies (no extra modules to install),
- uses standard python3 (standard, meaning: no extra libs),

Again: why? I work mostly in either C++ or Python projects and don't want to be forced to install nodejs (+dependencies) or another python tool (+dependencies).

## What it does?

The constrains above shaped the development to deliver a script which:

- needs a configuration to run - it is mandatory parameter. See [the example file](gitcclog.json) and read the help section which is inside,
- the script reads the specified configuration file and then uses git to scan the log for conventional commits messages and tags,
- if the changelog parameter in the file is set then it writes a complete changelog from the git history to that file,
- by default - it only generates file and **does not commit or tag**,
- with option `--real-run` it does the commit and tag,
- with option `--force-version` it is possible to specify arbitrary version for a tag.
- git hashes and issues in the changelog file can be links to an external project management system

## Requirements

- Python 3.10+
- git

## Usage

```bash
python3 gitcclog.py --config gitcclog.json
```

Or use the shell wrapper (assumes `gitcclog.json` in the current directory):

```bash
./gitcclog.sh
```

### CLI Options

| Option | Required | Description |
|---|---|---|
| `--config` | Yes | Path to the configuration JSON file |
| `--log-level` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL` |
| `--real-run` | No | Actually commit the changelog and create a git tag. Without this flag the tool runs in dry-run mode. |
| `--force-version` | No | Override the computed version with an arbitrary string |

### Examples

```bash
# dry run - generates changelog but does not commit or tag
python3 gitcclog.py --config gitcclog.json

# real run - commits and tags
python3 gitcclog.py --config gitcclog.json --real-run

# force a specific version
python3 gitcclog.py --config gitcclog.json --real-run --force-version 2.0.0
```

## Configuration

See [the example file](gitcclog.json). All keys:

| Key | Description |
|---|---|
| `tagPrefix` | Prefix for version tags, e.g. `"v"` results in `v1.0.0`. Only tags with this prefix are recognized from git history. |
| `initialNonPrefixedVersion` | Starting version when no tag exists yet. The prefix is added to it. |
| `changelogFile` | Output file for the changelog. Empty string `""` to skip generation. |
| `compareUrlFormat` | URL template for version comparison links. Placeholders: `{{previousTag}}`, `{{currentTag}}`. |
| `commitUrlFormat` | URL template for commit links. Placeholder: `{{hash}}`. |
| `issueUrlFormat` | URL template for issue links. Placeholder: `{{id}}`. |

## Version bumping

Version numbers are calculated from commit types following semver:

- **Breaking changes** (`!` marker or `BREAKING CHANGE` footer) bump **major**
- **Features** (`feat`) bump **minor**
- **Fixes and everything else** bump **patch**

## Supported commit types

`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `wip`, `chore`, `revert`

Only `feat`, `fix`, and breaking changes appear in the generated changelog.

Issue references are recognized from footers: `close`, `closes`, `fix`, `fixes`, `ref`, `refs`, `resolves`, `related work items`.

## Tests

```bash
python3 gitcclog_test.py
```

## About

Well, this little side-project started in mid-2024 and got almost completed pretty quickly. Then it staled for a year or so and now (2026) it was a good candidate to check it off using AI tools (copilot and a bit of claude). So one evening later here you the missing bits got fixed and it is ready to share. It is far from being perfect, but it does it job.
