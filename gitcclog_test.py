import unittest
from unittest.mock import patch, call

import gitcclog
import logging
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace


def _returncode(code, stderr=""):
    """Build a stand-in for a subprocess.CompletedProcess with a given returncode."""
    return SimpleNamespace(returncode=code, stderr=stderr, stdout="")


class TestGitComCon(unittest.TestCase):
    def setUp(self) -> None:
        logging.getLogger().setLevel(logging.FATAL)

        return super().setUp()

    def test_invalid_title(self):
        self.assertIsNone(gitcclog.parse_title(""))
        self.assertIsNone(gitcclog.parse_title("bla"))
        self.assertIsNone(gitcclog.parse_title("bla some more"))
        self.assertIsNone(gitcclog.parse_title("invalid_token: but valid message"))
        self.assertIsNone(gitcclog.parse_title("feat feat: valid tokens but 2"))
        self.assertIsNone(gitcclog.parse_title("feat : valid token but extra space"))
        self.assertIsNone(gitcclog.parse_title("feat (bla) : valid token but extra spaces"))
        self.assertIsNone(gitcclog.parse_title("feat (bla): valid token but extra spaces"))
        self.assertIsNone(gitcclog.parse_title("feat (bla):valid token but extra spaces"))
        self.assertIsNone(gitcclog.parse_title("feat(bla):valid token but too few spaces"))
        self.assertIsNone(gitcclog.parse_title("feat(bla)(a):valid token but extra context"))

    def test_valid_title(self):
        parsed = gitcclog.parse_title("feat: valid message")
        self.assertIsNotNone(parsed)
        assert parsed is not None  # for calming down IDE checker
        self.assertEqual(parsed["type"], "feat")
        self.assertIsNone(parsed["scope"])
        self.assertEqual(parsed["description"], "valid message")
        self.assertFalse(parsed["breaking"])

        parsed = gitcclog.parse_title("feat(bla): valid message")
        self.assertIsNotNone(parsed)
        assert parsed is not None  # for calming down IDE checker
        self.assertEqual(parsed["type"], "feat")
        self.assertEqual(parsed["scope"], "bla")
        self.assertEqual(parsed["description"], "valid message")
        self.assertFalse(parsed["breaking"])

        parsed = gitcclog.parse_title("feat(scope1, scope2): valid message")
        self.assertIsNotNone(parsed)
        assert parsed is not None  # for calming down IDE checker
        self.assertEqual(parsed["type"], "feat")
        self.assertEqual(parsed["scope"], "scope1, scope2")
        self.assertEqual(parsed["description"], "valid message")
        self.assertFalse(parsed["breaking"])

        parsed = gitcclog.parse_title("fix!: valid message")
        self.assertIsNotNone(parsed)
        assert parsed is not None  # for calming down IDE checker
        self.assertEqual(parsed["type"], "fix")
        self.assertIsNone(parsed["scope"])
        self.assertEqual(parsed["description"], "valid message")
        self.assertTrue(parsed["breaking"])

        parsed = gitcclog.parse_title("fix(scope)!: valid message")
        self.assertIsNotNone(parsed)
        assert parsed is not None  # for calming down IDE checker
        self.assertEqual(parsed["type"], "fix")
        self.assertEqual(parsed["scope"], "scope")
        self.assertEqual(parsed["description"], "valid message")
        self.assertTrue(parsed["breaking"])

    def test_tag_value(self):
        self.assertEqual(gitcclog.tag_to_numbers("v1.2.3", prefix="v"), [1, 2, 3])
        self.assertEqual(gitcclog.tag_to_numbers("3.4.5"), [3, 4, 5])
        # it raises exception if it cannot convert the tag to numbers
        self.assertRaises(ValueError, gitcclog.tag_to_numbers, "v1.2.3")
        self.assertRaises(ValueError, gitcclog.tag_to_numbers, "va.2.3")

    def test_get_next_tag(self):
        self.assertEqual(gitcclog.get_next_tag(None, breaking_changes=False, new_features=False), "0.0.0")
        self.assertEqual(gitcclog.get_next_tag("1.2.3", breaking_changes=False, new_features=False), "1.2.4")
        self.assertEqual(gitcclog.get_next_tag("1.2.3", breaking_changes=False, new_features=True), "1.3.0")
        self.assertEqual(gitcclog.get_next_tag("1.2.3", breaking_changes=True, new_features=False), "2.0.0")
        self.assertEqual(gitcclog.get_next_tag("1.2.3", breaking_changes=True, new_features=True), "2.0.0")

    def test_get_naked_tag(self):
        self.assertEqual(gitcclog.get_naked_tag("v1.2.3", prefix="v"), "1.2.3")
        self.assertEqual(gitcclog.get_naked_tag("1.2.3"), "1.2.3")
        self.assertEqual(gitcclog.get_naked_tag("ver1.2.3", prefix="ver"), "1.2.3")


class TestParseFooters(unittest.TestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.FATAL)

    def test_empty_body(self):
        self.assertEqual(gitcclog.parse_footers(""), [])

    def test_breaking_change_footer(self):
        footers = gitcclog.parse_footers("BREAKING CHANGE: removed old api")
        self.assertEqual(len(footers), 1)
        self.assertEqual(footers[0]["key"], "BREAKING CHANGE")
        self.assertEqual(footers[0]["value"], "removed old api")

    def test_closes_footer(self):
        footers = gitcclog.parse_footers("Closes: #123")
        self.assertEqual(len(footers), 1)
        self.assertEqual(footers[0]["key"], "Closes")
        self.assertEqual(footers[0]["value"], "#123")

    def test_multiple_footers(self):
        body = "BREAKING CHANGE: new api\nCloses: #42\nRefs: #99"
        footers = gitcclog.parse_footers(body)
        self.assertEqual(len(footers), 3)

    def test_non_footer_lines_ignored(self):
        body = "This is just a description\nwith multiple lines\nCloses: #42"
        footers = gitcclog.parse_footers(body)
        self.assertEqual(len(footers), 1)
        self.assertEqual(footers[0]["key"], "Closes")

    def test_non_footer_lines_ignored2(self):
        body = "merged-PR: !10936\nRelated work items: #50010"

        footers = gitcclog.parse_footers(body)
        self.assertEqual(len(footers), 2)
        self.assertEqual(footers[0]["key"], "merged-PR")
        self.assertEqual(footers[1]["key"], "Related work items")


class TestGenerateChangelog(unittest.TestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.FATAL)
        self.tmpdir = tempfile.mkdtemp()
        self.changelog_path = os.path.join(self.tmpdir, "CHANGELOG.md")
        self.base_config = {
            "tagPrefix": "",
            "initialNonPrefixedVersion": "0.1.0",
            "changelogFile": self.changelog_path,
            "compareUrlFormat": "",
            "commitUrlFormat": "",
            "issueUrlFormat": "",
        }

    def tearDown(self):
        if os.path.exists(self.changelog_path):
            os.remove(self.changelog_path)
        os.rmdir(self.tmpdir)

    def test_basic_feature_changelog(self):
        history = {
            "commits": [
                {
                    "full_hash": "abc1234567890",
                    "short_hash": "abc1234",
                    "committer_date": "2025-01-15 10:00:00 +0000",
                    "tags": [],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "add login", "breaking": False},
                }
            ],
            "lastTag": None,
        }
        result = gitcclog.generate_changelog(history, self.base_config)
        self.assertEqual(result, "0.1.0")
        with open(self.changelog_path) as f:
            content = f.read()
        self.assertIn("# Changelog", content)
        self.assertIn("0.1.0", content)

    def test_changelog_with_urls_and_issues(self):
        config = {**self.base_config,
                  "commitUrlFormat": "https://example.com/commit/{{hash}}",
                  "issueUrlFormat": "https://example.com/issues/{{id}}",
                  }
        history = {
            "commits": [
                {
                    "full_hash": "abc1234567890",
                    "short_hash": "abc1234",
                    "committer_date": "2025-01-15 10:00:00 +0000",
                    "tags": [],
                    "footers": [{"key": "Closes", "value": "#42"}],
                    "title": {"type": "feat", "scope": None, "description": "add feature", "breaking": False},
                },
                {
                    "full_hash": "def7890123456",
                    "short_hash": "def7890",
                    "committer_date": "2025-01-10 10:00:00 +0000",
                    "tags": ["0.1.0"],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "initial feature", "breaking": False},
                },
            ],
            "lastTag": "0.1.0",
        }
        gitcclog.generate_changelog(history, config)
        with open(self.changelog_path) as f:
            content = f.read()
        self.assertIn("[abc1234](https://example.com/commit/abc1234567890)", content)
        self.assertIn("[#42](https://example.com/issues/42)", content)
        self.assertIn("closes", content)

    def test_changelog_breaking_change_bumps_major(self):
        history = {
            "commits": [
                {
                    "full_hash": "bbb2222222222",
                    "short_hash": "bbb2222",
                    "committer_date": "2025-01-15 10:00:00 +0000",
                    "tags": [],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "new api", "breaking": True},
                },
                {
                    "full_hash": "aaa1111111111",
                    "short_hash": "aaa1111",
                    "committer_date": "2025-01-10 10:00:00 +0000",
                    "tags": ["1.0.0"],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "initial", "breaking": False},
                },
            ],
            "lastTag": "1.0.0",
        }
        result = gitcclog.generate_changelog(history, self.base_config)
        self.assertEqual(result, "2.0.0")
        with open(self.changelog_path) as f:
            content = f.read()
        self.assertIn("2.0.0", content)
        self.assertIn("BREAKING CHANGES", content)

    def test_changelog_fix_bumps_patch(self):
        history = {
            "commits": [
                {
                    "full_hash": "ccc3333333333",
                    "short_hash": "ccc3333",
                    "committer_date": "2025-01-15 10:00:00 +0000",
                    "tags": [],
                    "footers": [],
                    "title": {"type": "fix", "scope": None, "description": "fix crash", "breaking": False},
                },
                {
                    "full_hash": "aaa1111111111",
                    "short_hash": "aaa1111",
                    "committer_date": "2025-01-10 10:00:00 +0000",
                    "tags": ["1.0.0"],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "initial", "breaking": False},
                },
            ],
            "lastTag": "1.0.0",
        }
        result = gitcclog.generate_changelog(history, self.base_config)
        self.assertEqual(result, "1.0.1")

    def test_changelog_empty_changelog_file_skips_write(self):
        config = {**self.base_config, "changelogFile": ""}
        history = {
            "commits": [],
            "lastTag": None,
        }
        result = gitcclog.generate_changelog(history, config)
        self.assertEqual(result, "0.1.0")
        self.assertFalse(os.path.exists(self.changelog_path))

    def test_changelog_with_scoped_commits(self):
        history = {
            "commits": [
                {
                    "full_hash": "abc1234567890",
                    "short_hash": "abc1234",
                    "committer_date": "2025-01-15 10:00:00 +0000",
                    "tags": [],
                    "footers": [],
                    "title": {"type": "feat", "scope": "auth", "description": "add oauth", "breaking": False},
                },
                {
                    "full_hash": "def7890123456",
                    "short_hash": "def7890",
                    "committer_date": "2025-01-10 10:00:00 +0000",
                    "tags": ["1.0.0"],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "initial", "breaking": False},
                },
            ],
            "lastTag": "1.0.0",
        }
        gitcclog.generate_changelog(history, self.base_config)
        with open(self.changelog_path) as f:
            content = f.read()
        self.assertIn("(auth) add oauth", content)

    def test_changelog_with_compare_url(self):
        config = {**self.base_config,
                  "compareUrlFormat": "https://example.com/compare/{{previousTag}}...{{currentTag}}",
                  }
        history = {
            "commits": [
                {
                    "full_hash": "bbb2222222222",
                    "short_hash": "bbb2222",
                    "committer_date": "2025-01-15 10:00:00 +0000",
                    "tags": [],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "new thing", "breaking": False},
                },
                {
                    "full_hash": "aaa1111111111",
                    "short_hash": "aaa1111",
                    "committer_date": "2025-01-10 10:00:00 +0000",
                    "tags": ["1.0.0"],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "initial", "breaking": False},
                },
            ],
            "lastTag": "1.0.0",
        }
        gitcclog.generate_changelog(history, config)
        with open(self.changelog_path) as f:
            content = f.read()
        self.assertIn("https://example.com/compare/1.0.0...1.1.0", content)

    def test_new_release_has_date(self):
        history = {
            "commits": [
                {
                    "full_hash": "bbb2222222222",
                    "short_hash": "bbb2222",
                    "committer_date": "2025-03-20 10:00:00 +0000",
                    "tags": [],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "new thing", "breaking": False},
                },
                {
                    "full_hash": "aaa1111111111",
                    "short_hash": "aaa1111",
                    "committer_date": "2025-01-10 10:00:00 +0000",
                    "tags": ["1.0.0"],
                    "footers": [],
                    "title": {"type": "feat", "scope": None, "description": "initial", "breaking": False},
                },
            ],
            "lastTag": "1.0.0",
        }
        gitcclog.generate_changelog(history, self.base_config)
        with open(self.changelog_path) as f:
            content = f.read()
        self.assertIn("1.1.0", content)
        self.assertIn("(2025-03-20)", content)


class TestCommitAndTag(unittest.TestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.FATAL)

    @patch("gitcclog.subprocess.run")
    def test_commit_and_tag_runs_git_commands(self, mock_run):
        # add: ok, diff --cached --quiet: 1 (changes staged), commit: ok, tag: ok
        mock_run.side_effect = [
            _returncode(0), _returncode(1), _returncode(0), _returncode(0),
        ]
        result = gitcclog.commit_and_tag("CHANGELOG.md", "v", "1.2.0")
        self.assertEqual(result, "released")
        expected_calls = [
            call(["git", "add", "CHANGELOG.md"], capture_output=True, text=True),
            call(["git", "diff", "--cached", "--quiet"], capture_output=True, text=True),
            call(["git", "commit", "-m", "chore(release): v1.2.0"], capture_output=True, text=True),
            call(["git", "tag", "v1.2.0"], capture_output=True, text=True),
        ]
        mock_run.assert_has_calls(expected_calls)

    @patch("gitcclog.subprocess.run")
    def test_commit_and_tag_no_prefix(self, mock_run):
        mock_run.side_effect = [
            _returncode(0), _returncode(1), _returncode(0), _returncode(0),
        ]
        result = gitcclog.commit_and_tag("CHANGELOG.md", "", "1.2.0")
        self.assertEqual(result, "released")
        expected_calls = [
            call(["git", "add", "CHANGELOG.md"], capture_output=True, text=True),
            call(["git", "diff", "--cached", "--quiet"], capture_output=True, text=True),
            call(["git", "commit", "-m", "chore(release): 1.2.0"], capture_output=True, text=True),
            call(["git", "tag", "1.2.0"], capture_output=True, text=True),
        ]
        mock_run.assert_has_calls(expected_calls)

    @patch("gitcclog.subprocess.run")
    def test_commit_and_tag_fails_on_git_error(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error"
        result = gitcclog.commit_and_tag("CHANGELOG.md", "", "1.2.0")
        self.assertEqual(result, "failed")


class TestCommitAndTagNoop(unittest.TestCase):
    """When the changelog is unchanged, releasing must be a no-op, not a failure."""

    def setUp(self):
        logging.getLogger().setLevel(logging.FATAL)
        self.origin_cwd = os.getcwd()
        self.repo = tempfile.mkdtemp()
        os.chdir(self.repo)
        self._git("init")
        self._git("config", "user.email", "t@t.t")
        self._git("config", "user.name", "t")
        with open("CHANGELOG.md", "w") as f:
            f.write("# Changelog\n")
        self._git("add", "CHANGELOG.md")
        self._git("commit", "-m", "chore(release): 1.2.2")

    def tearDown(self):
        os.chdir(self.origin_cwd)
        shutil.rmtree(self.repo)

    def _git(self, *args):
        subprocess.run(["git", *args], capture_output=True, text=True, check=True)

    def test_unchanged_changelog_is_noop_not_failure(self):
        # CHANGELOG.md already committed and untouched -> nothing to commit.
        result = gitcclog.commit_and_tag("CHANGELOG.md", "", "1.2.3")
        self.assertEqual(result, "noop")

    def test_unchanged_changelog_creates_no_tag(self):
        gitcclog.commit_and_tag("CHANGELOG.md", "", "1.2.3")
        tags = subprocess.run(["git", "tag"], capture_output=True, text=True)
        self.assertEqual(tags.stdout.strip(), "")

    def test_changed_changelog_commits_and_tags(self):
        with open("CHANGELOG.md", "w") as f:
            f.write("# Changelog\n\nnew content\n")
        result = gitcclog.commit_and_tag("CHANGELOG.md", "", "1.2.3")
        self.assertEqual(result, "released")
        tags = subprocess.run(["git", "tag"], capture_output=True, text=True)
        self.assertEqual(tags.stdout.strip(), "1.2.3")


class TestMainFlow(unittest.TestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.FATAL)
        self.tmpdir = tempfile.mkdtemp()
        self.changelog_path = os.path.join(self.tmpdir, "CHANGELOG.md")

    def tearDown(self):
        if os.path.exists(self.changelog_path):
            os.remove(self.changelog_path)
        os.rmdir(self.tmpdir)

    @patch("gitcclog.commit_and_tag")
    @patch("gitcclog.get_git_history")
    def test_dry_run_does_not_commit(self, mock_history, mock_commit):
        mock_history.return_value = ""
        config = {
            "tagPrefix": "",
            "initialNonPrefixedVersion": "0.1.0",
            "changelogFile": self.changelog_path,
            "compareUrlFormat": "",
            "commitUrlFormat": "",
            "issueUrlFormat": "",
        }
        new_tag = gitcclog.generate_changelog({"commits": [], "lastTag": None}, config)
        gitcclog.run(config, new_tag, real_run=False, changelog_file=self.changelog_path)
        mock_commit.assert_not_called()

    @patch("gitcclog.commit_and_tag", return_value="released")
    @patch("gitcclog.get_git_history")
    def test_no_dry_run_commits(self, mock_history, mock_commit):
        mock_history.return_value = ""
        config = {
            "tagPrefix": "v",
            "initialNonPrefixedVersion": "0.1.0",
            "changelogFile": self.changelog_path,
            "compareUrlFormat": "",
            "commitUrlFormat": "",
            "issueUrlFormat": "",
        }
        gitcclog.run(config, "0.1.0", real_run=True, changelog_file=self.changelog_path)
        mock_commit.assert_called_once_with(self.changelog_path, "v", "0.1.0")

    @patch("gitcclog.commit_and_tag", return_value="released")
    def test_force_version_overrides_computed(self, mock_commit):
        config = {
            "tagPrefix": "v",
            "initialNonPrefixedVersion": "0.1.0",
            "changelogFile": self.changelog_path,
            "compareUrlFormat": "",
            "commitUrlFormat": "",
            "issueUrlFormat": "",
        }
        # Force version "9.9.9" instead of whatever was computed
        gitcclog.run(config, "9.9.9", real_run=True, changelog_file=self.changelog_path)
        mock_commit.assert_called_once_with(self.changelog_path, "v", "9.9.9")


class TestParseRawCommits(unittest.TestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.FATAL)

    def test_parses_single_feat_commit(self):
        raw = "abc1234567890(abc1234)()(2025-01-15 10:00:00 +0000)\nfeat: add login\n" + gitcclog.SCISSORS
        history = gitcclog.parse_raw_commits(raw, "")
        self.assertEqual(len(history["commits"]), 1)
        self.assertEqual(history["commits"][0]["title"]["type"], "feat")
        self.assertEqual(history["commits"][0]["title"]["description"], "add login")

    def test_parses_tagged_commit(self):
        raw = "abc1234567890(abc1234)(tag: 1.0.0)(2025-01-15 10:00:00 +0000)\nfeat: add login\n" + gitcclog.SCISSORS
        history = gitcclog.parse_raw_commits(raw, "")
        self.assertEqual(history["lastTag"], "1.0.0")
        self.assertEqual(history["commits"][0]["tags"], ["1.0.0"])

    def test_keeps_non_conventional_commits_as_chore(self):
        raw = "abc1234567890(abc1234)()(2025-01-15 10:00:00 +0000)\njust a regular message\n" + gitcclog.SCISSORS
        history = gitcclog.parse_raw_commits(raw, "")
        self.assertEqual(len(history["commits"]), 1)
        self.assertEqual(history["commits"][0]["title"]["type"], "chore")
        self.assertEqual(history["commits"][0]["title"]["description"], "just a regular message")

    def test_parses_commit_with_tag_prefix(self):
        raw = "abc1234567890(abc1234)(tag: v1.0.0)(2025-01-15 10:00:00 +0000)\nfeat: thing\n" + gitcclog.SCISSORS
        history = gitcclog.parse_raw_commits(raw, "v")
        self.assertEqual(history["lastTag"], "v1.0.0")

    def test_empty_input(self):
        history = gitcclog.parse_raw_commits("", "")
        self.assertEqual(len(history["commits"]), 0)
        self.assertIsNone(history["lastTag"])


if __name__ == '__main__':
    unittest.main()
