import argparse
import json
import logging as log
import re
import subprocess

# no spaces (because of split)
SCISSORS = "------------------------>8------------------------"


def get_git_history(commit_from: str | None, commit_to: str | None) -> str | None:
    """
    Use subprocess to call git log command to fetch entries.
    @return: string with commit messages or None if there was an error

    getting log entries between commits
    %H - full hash
    %h - short hash (using --abbrev=... to specify length)
    %D - decorations like tags
    %ci - committer date, iso 8601 style
    %n - newline
    %B - raw title and body
    """
    cmd = "git log --decorate --no-color --date-order --abbrev=7 --format=%H(%h)(%D)(%ci)%n%B" + SCISSORS
    if commit_from is not None and commit_to is not None:
        cmd += " " + commit_from + ".." + commit_to

    log.debug("Running command: %s", cmd)
    res = subprocess.run(cmd.split(" "), capture_output=True, text=True)

    if res.returncode != 0:
        log.error("Cannot get commit messages: %s (args: %s)", res.stderr, res.args)
        return None

    return res.stdout


def tag_to_numbers(tag: str, prefix: str = "") -> list[int]:
    """
    Converts a tag string to a tuple of integers for comparison.
    """
    value_to_compare = [int(sub_tag_str) for sub_tag_str in tag[len(prefix):].split('.')]
    return value_to_compare


def parse_title(title: str) -> dict | None:
    """
    Parse the commit title according to the Conventional Commits specification and return a dictionary with parsed data.
    """
    pattern = r'^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>([!]))?: (?P<description>.+)$'
    parsed = re.match(pattern, title)

    if parsed is None:
        log.debug("Cannot parse commit title: %s", title)
        return None

    res = parsed.groupdict()
    res["breaking"] = res["breaking"] is not None  # set it as bool if it was matched

    valid_types = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "wip", "chore", "revert"]
    if res["type"] not in valid_types:
        log.debug("Invalid commit type: %s", res["type"])
        return None

    return res


def parse_footers(body: str) -> list[dict]:
    """
    Parse the commit body and return a list of dictionaries with parsed data.
    """
    footers = []
    pattern = r'^(?P<key>[a-zA-Z- ]+|BREAKING CHANGE): (?P<value>.+)$'
    for line in body.split("\n"):
        parsed = re.match(pattern, line)
        if parsed is not None:
            footer = parsed.groupdict()
            footers.append(footer)
    return footers


def parse_raw_commits(raw_commit_messages: str, tag_prefix: str) -> dict:
    """
    Parse the raw commit messages and return a list of dictionaries with parsed data.
    """
    history = {
        "commits": [],
        "lastTag": None
    }
    raw_commits = raw_commit_messages.split(SCISSORS)
    for commit in raw_commits:
        splitted = commit.strip().split("\n")
        if len(splitted) < 2:
            continue
        commit_line = splitted[0]
        title = splitted[1]
        body = "\n".join(splitted[2:])

        splitted_commit_line = re.match(r"^([0-9a-f]+)\(([0-9a-f]+)\)\((.*)\)\((.*)\)", commit_line)
        if splitted_commit_line is not None:
            full_hash = splitted_commit_line.group(1)
            short_hash = splitted_commit_line.group(2)

            # get all decorations
            decorations = [decor.strip() for decor in splitted_commit_line.group(3).split(",") if decor.strip() != ""]
            # leave only tags
            all_tags = [decor.replace("tag: ", "") for decor in decorations if decor.startswith("tag: ")]
            # filter only tags with the given prefix and has a valid numerical form
            tags = [tag for tag in all_tags if re.match(tag_prefix + r"\d+\.\d+\.\d+", tag) is not None]
            # sort tags by version
            tags.sort(key=lambda tag_str: tag_to_numbers(tag_str, tag_prefix))

            if len(tags) > 0:
                max_tag = max(tags, key=lambda tag_str: tag_to_numbers(tag_str, tag_prefix))

                if history["lastTag"] is None or \
                        tag_to_numbers(max_tag, tag_prefix) > tag_to_numbers(history["lastTag"], tag_prefix):
                    history["lastTag"] = max_tag
                    log.debug("New last tag: %s", max_tag)

            committer_date = splitted_commit_line.group(4)

            title_parsed = parse_title(title)

            if title_parsed is None:
                # try again prefixing with "chore: " to decrease a chance of missing non-conform lines, but with tags
                title_parsed = parse_title("chore: " + title)
                if title_parsed is None:
                    continue

            footers_parsed = parse_footers(body)

            commit_message = {
                "full_hash": full_hash,
                "short_hash": short_hash,
                "committer_date": committer_date,
                "tags": tags,
                "footers": footers_parsed,
                "title": title_parsed
            }
            history["commits"].append(commit_message)
        else:
            log.debug("Cannot parse commit line: %s", commit_line)

    return history


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Configuration file - it is required.", required=True)
    parser.add_argument("--log-level", help="Log level, default: %(default)s", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument("--real-run", help="Commit and tag, default: False", action="store_true")
    parser.add_argument("--force-version", help="Force given version.", default="")

    return parser.parse_args()


def get_config(path: str) -> dict:
    """
    Read the configuration json file and return the data as a dictionary.
    """
    with open(path) as f:
        data = json.load(f)
    return data


def get_naked_tag(tag: str, prefix: str = "") -> str:
    """
    Get the tag without the prefix.
    @param tag: the tag with the prefix
    @param tag_prefix: the prefix
    @return: the tag without the prefix
    """
    return tag[len(prefix):]


def get_next_tag(previous_naked_tag: str | None, breaking_changes: bool, new_features: bool) -> str:
    """
    Get the next tag based on the previous tag and the changes.
    If the previous tag is None, it returns "0.0.0".
    If there are no changes it treats it as a fix and increments the last number.
    @param previous_naked_tag: the previous tag without the prefix
    @param breaking_changes: if there are breaking changes
    @param new_features: if there are new features
    @param new_fixes: if there are new fixes
    @return: the next tag as string
    """
    if previous_naked_tag is None:
        return "0.0.0"

    tag_parts = [int(part) for part in previous_naked_tag.split(".")]

    if breaking_changes:
        tag_parts[0] += 1
        tag_parts[1] = 0
        tag_parts[2] = 0
    elif new_features:
        tag_parts[1] += 1
        tag_parts[2] = 0
    else:
        tag_parts[2] += 1

    return ".".join([str(part) for part in tag_parts])


def generate_changelog(history: dict, config: dict) -> str:
    """
    Generate the changelog based on the parsed commits and the configuration.
    """
    current_tag_commits = {
        "tag": None,
        "breaking_changes": [],
        "features": [],
        "fixes": []
    }

    releases = []

    for commit in reversed(history["commits"]):
        if commit["title"]["breaking"]:
            current_tag_commits["breaking_changes"].append(commit["title"]["description"])

        for footer in commit["footers"]:
            if footer["key"] == "BREAKING CHANGE":
                current_tag_commits["breaking_changes"].append(footer["value"])

        if commit["title"]["type"] == "feat" or commit["title"]["type"] == "fix":
            scope = f"({commit['title']['scope']}) " if commit['title']['scope'] else ""
            description = f"{scope}{commit['title']['description']}"
            if config["commitUrlFormat"]:
                commit_url = config["commitUrlFormat"]\
                    .replace("{{hash}}", commit['full_hash'])
                description += f" ([{commit['short_hash']}]({commit_url})"

            # Look for closing issues in footers
            closes_refs = []
            for footer in commit["footers"]:
                if footer["key"].lower() in ["close", "closes", "fix", "fixes", "ref", "refs", "resolves", "related work items"]:  # noqa: E501 ignore too long line
                    refs = re.split(r'[,\s]+', footer["value"])
                    for ref in refs:
                        issue_match = re.search(r'#+(\d+)', ref)
                        if issue_match and config["issueUrlFormat"]:
                            issue_id = issue_match.group(1)
                            issue_url = config["issueUrlFormat"]\
                                .replace("{{id}}", issue_id)
                            closes_refs.append(f"[#{issue_id}]({issue_url})")

            if config["commitUrlFormat"]:
                description += ")"

            # Add closing references if any found
            if closes_refs:
                description += f", closes {' '.join(closes_refs)}"

            if commit["title"]["type"] == "feat":
                current_tag_commits["features"].append(description)
            else:
                current_tag_commits["fixes"].append(description)

        if len(commit["tags"]) > 0:
            current_tag_commits["tag"] = commit["tags"][-1]
            releases.append(current_tag_commits)
            current_tag_commits = {
                "tag": None,
                "breaking_changes": [],
                "features": [],
                "fixes": []
            }

    # Calculate the new version
    last_tag = history["lastTag"]
    if last_tag is None:
        new_naked_tag = config["initialNonPrefixedVersion"]
    else:
        breaking_changes = len(current_tag_commits["breaking_changes"]) > 0
        new_features = len(current_tag_commits["features"]) > 0
        new_naked_tag = get_next_tag(get_naked_tag(last_tag, config["tagPrefix"]), breaking_changes, new_features)

    current_tag_commits["tag"] = config["tagPrefix"] + new_naked_tag
    releases.append(current_tag_commits)

    # Reverse releases to have newest first
    releases.reverse()

    # Generate markdown content
    if config["changelogFile"].strip() != "":
        with open(config["changelogFile"], "w") as f:
            f.write("# Changelog\n\n")
            f.write("All notable changes to this project will be documented in this file.\n\n")

            for i, release in enumerate(releases):
                if release["tag"] is None:
                    continue

                first_release = (i == len(releases) - 1)

                # Add version header with compare URL if available
                version_line = "## "
                if config["compareUrlFormat"] and not first_release:
                    next_tag = releases[i + 1]["tag"]
                    compare_url = config["compareUrlFormat"]\
                        .replace("{{previousTag}}", next_tag)\
                        .replace("{{currentTag}}", release["tag"])
                    version_line += f"[{release['tag']}]({compare_url})"
                else:
                    version_line += release["tag"]

                # Add date from the latest commit in this release
                for commit in history["commits"]:
                    if release["tag"] in commit["tags"]:
                        date = commit["committer_date"].split()[0]  # Get just the date part
                        version_line += f" ({date})"
                        break

                f.write(f"{version_line}\n\n\n")

                if first_release:
                    f.write("This is the first release, so the lists of features and bugs is empty.\n\n")
                else:
                    # Add breaking changes
                    if release["breaking_changes"]:
                        f.write("### BREAKING CHANGES\n\n")
                        for change in release["breaking_changes"]:
                            f.write(f"* {change}\n")
                        f.write("\n")

                    # Add features
                    if release["features"]:
                        f.write("### Features\n\n")
                        for feature in sorted(release["features"], key=str.casefold):
                            f.write(f"* {feature}\n")
                        f.write("\n\n")

                    # Add fixes
                    if release["fixes"]:
                        f.write("### Bug Fixes\n\n")
                        for fix in sorted(release["fixes"], key=str.casefold):
                            f.write(f"* {fix}\n")
                        f.write("\n")

    return new_naked_tag


def commit_and_tag(changelog_file: str, tag_prefix: str, naked_tag: str) -> bool:
    """
    Stage the changelog file, commit with a release message, and create a git tag.
    Returns True on success, False on failure.
    """
    full_tag = tag_prefix + naked_tag

    steps = [
        (["git", "add", changelog_file], f"staging {changelog_file}"),
        (["git", "commit", "-m", f"chore(release): {full_tag}"], f"committing release {full_tag}"),
        (["git", "tag", full_tag], f"tagging {full_tag}"),
    ]

    for cmd, description in steps:
        log.debug("Running: %s", " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            log.error("Failed %s: %s", description, res.stderr)
            return False

    return True


def run(config: dict, new_naked_tag: str, real_run: bool, changelog_file: str) -> None:
    """
    Execute the release: either commit+tag (real_run) or print dry-run info.
    """
    full_tag = config["tagPrefix"] + new_naked_tag

    if not real_run:
        log.info("Dry run: would release %s", full_tag)
        return

    if changelog_file.strip() == "":
        log.info("No changelog file configured, skipping commit.")
        return

    success = commit_and_tag(changelog_file, config["tagPrefix"], new_naked_tag)
    if success:
        log.info("Released %s", full_tag)
    else:
        log.error("Release failed for %s", full_tag)
        exit(1)


if __name__ == "__main__":
    args = get_args()

    log.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
    log.getLogger().setLevel(args.log_level)

    config = get_config(args.config)

    git_history = get_git_history(commit_from=None, commit_to=None)
    if git_history is None:
        log.error("Cannot get commit messages.")
        exit(1)

    history = parse_raw_commits(git_history, config["tagPrefix"])
    # print(git_history)

    new_naked_tag = generate_changelog(history, config)

    if args.force_version:
        new_naked_tag = args.force_version

    run(config, new_naked_tag, args.real_run, config["changelogFile"])
