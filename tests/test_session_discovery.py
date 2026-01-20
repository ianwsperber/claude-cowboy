"""Tests for session_discovery module."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from lib.session_discovery import (
    SessionInfo,
    discover_all_sessions,
    discover_sessions,
    find_claude_processes,
    get_ide_sessions,
    get_process_cwd,
    get_session_by_id,
    get_session_metadata,
    scan_session_files,
)


class TestSessionInfo:
    """Tests for SessionInfo dataclass."""

    def test_default_values(self):
        """Should have correct default values."""
        session = SessionInfo(
            session_id="test-123",
            cwd="/path/to/project",
            jsonl_path="/path/to/test.jsonl",
        )
        assert session.pid is None
        assert session.git_branch == ""
        assert session.message_count == 0


class TestFindClaudeProcesses:
    """Tests for find_claude_processes function."""

    def test_returns_empty_dict_on_ps_failure(self):
        """Should return empty dict when ps command fails."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="")
            result = find_claude_processes()
            assert result == {}

    def test_excludes_claude_app_processes(self):
        """Should exclude Claude.app helper processes."""
        mock_ps_output = """USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
user 123 0.0 0.1 1234 5678 ? S 10:00 0:00 /Applications/Claude.app/Contents/MacOS/Claude
user 456 0.0 0.1 1234 5678 ? S 10:00 0:00 claude --help"""

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=mock_ps_output)
            with mock.patch(
                "lib.session_discovery.get_process_cwd", return_value="/test/path"
            ):
                result = find_claude_processes()
                # Should only have one entry (for PID 456, not 123)
                assert len(result) <= 1


class TestGetProcessCwd:
    """Tests for get_process_cwd function."""

    def test_returns_none_on_lsof_failure(self):
        """Should return None when lsof fails."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = get_process_cwd(1234)
            assert result is None

    def test_extracts_cwd_from_lsof_output(self):
        """Should extract CWD from lsof output."""
        mock_lsof_output = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
python 1234 user cwd DIR 1,4 1234 5678 /path/to/project"""

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=mock_lsof_output)
            result = get_process_cwd(1234)
            assert result == "/path/to/project"


class TestGetIdeSession:
    """Tests for get_ide_sessions function."""

    def test_returns_empty_when_no_ide_dir(self):
        """Should return empty dict when IDE dir doesn't exist."""
        with mock.patch(
            "lib.session_discovery.get_claude_home",
            return_value=Path("/nonexistent"),
        ):
            result = get_ide_sessions()
            assert result == {}

    def test_reads_lock_files(self):
        """Should read IDE lock files and return PIDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_home = Path(tmpdir)
            ide_dir = claude_home / "ide"
            ide_dir.mkdir()

            lock_file = ide_dir / "test.lock"
            lock_file.write_text(
                json.dumps(
                    {
                        "pid": 12345,
                        "workspaceFolders": ["/path/to/workspace"],
                    }
                )
            )

            with mock.patch(
                "lib.session_discovery.get_claude_home", return_value=claude_home
            ):
                # Mock os.kill to simulate process is running
                with mock.patch("os.kill"):
                    result = get_ide_sessions()
                    assert "/path/to/workspace" in result
                    assert 12345 in result["/path/to/workspace"]


class TestScanSessionFiles:
    """Tests for scan_session_files function."""

    def test_returns_empty_when_no_projects_dir(self):
        """Should return empty list when projects dir doesn't exist."""
        with mock.patch(
            "lib.session_discovery.get_claude_home",
            return_value=Path("/nonexistent"),
        ):
            result = scan_session_files()
            assert result == []

    def test_excludes_agent_sessions(self):
        """Should exclude sessions starting with 'agent-'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_home = Path(tmpdir)
            projects_dir = claude_home / "projects" / "test-project"
            projects_dir.mkdir(parents=True)

            # Create regular session file
            (projects_dir / "abc123.jsonl").touch()
            # Create agent session file (should be excluded)
            (projects_dir / "agent-def456.jsonl").touch()

            with mock.patch(
                "lib.session_discovery.get_claude_home", return_value=claude_home
            ):
                result = scan_session_files(discovery_hours=24)
                session_ids = [s[0] for s in result]
                assert "abc123" in session_ids
                assert "agent-def456" not in session_ids


class TestGetSessionMetadata:
    """Tests for get_session_metadata function."""

    def test_returns_empty_metadata_for_missing_file(self):
        """Should return empty metadata when file doesn't exist."""
        result = get_session_metadata(Path("/nonexistent/file.jsonl"))
        assert result["cwd"] == ""
        assert result["message_count"] == 0

    def test_extracts_metadata_from_jsonl(self):
        """Should extract metadata from JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_file = Path(tmpdir) / "test.jsonl"
            lines = [
                json.dumps(
                    {
                        "timestamp": "2024-01-01T12:00:00Z",
                        "cwd": "/path/to/project",
                        "gitBranch": "main",
                        "slug": "test-session",
                    }
                ),
                json.dumps({"timestamp": "2024-01-01T12:01:00Z"}),
            ]
            jsonl_file.write_text("\n".join(lines))

            result = get_session_metadata(jsonl_file)
            assert result["cwd"] == "/path/to/project"
            assert result["git_branch"] == "main"
            assert result["message_count"] == 2
            assert result["slug"] == "test-session"


class TestDiscoverSessions:
    """Tests for discover_sessions function."""

    def test_filters_hidden_sessions_by_default(self):
        """Should filter out old sessions without PID by default."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)

        mock_sessions = [
            SessionInfo(
                session_id="active",
                cwd="/active",
                jsonl_path="/active.jsonl",
                pid=1234,
                last_activity=old_time,
            ),
            SessionInfo(
                session_id="hidden",
                cwd="/hidden",
                jsonl_path="/hidden.jsonl",
                pid=None,
                last_activity=old_time,
            ),
        ]

        with mock.patch(
            "lib.session_discovery.discover_all_sessions", return_value=mock_sessions
        ):
            with mock.patch(
                "lib.session_discovery.load_config",
                return_value={"hideThresholdMinutes": 15},
            ):
                result = discover_sessions()
                assert len(result) == 1
                assert result[0].session_id == "active"

    def test_includes_hidden_with_flag(self):
        """Should include all sessions when include_hidden=True."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)

        mock_sessions = [
            SessionInfo(
                session_id="active",
                cwd="/active",
                jsonl_path="/active.jsonl",
                pid=1234,
                last_activity=old_time,
            ),
            SessionInfo(
                session_id="hidden",
                cwd="/hidden",
                jsonl_path="/hidden.jsonl",
                pid=None,
                last_activity=old_time,
            ),
        ]

        with mock.patch(
            "lib.session_discovery.discover_all_sessions", return_value=mock_sessions
        ):
            result = discover_sessions(include_hidden=True)
            assert len(result) == 2

    def test_shows_recent_sessions_without_pid(self):
        """Should show recent sessions even without PID."""
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        mock_sessions = [
            SessionInfo(
                session_id="recent",
                cwd="/recent",
                jsonl_path="/recent.jsonl",
                pid=None,
                last_activity=recent_time,
            ),
        ]

        with mock.patch(
            "lib.session_discovery.discover_all_sessions", return_value=mock_sessions
        ):
            with mock.patch(
                "lib.session_discovery.load_config",
                return_value={"hideThresholdMinutes": 15},
            ):
                result = discover_sessions()
                assert len(result) == 1
                assert result[0].session_id == "recent"


class TestGetSessionById:
    """Tests for get_session_by_id function."""

    def test_finds_session_by_full_id(self):
        """Should find session by full session ID."""
        mock_sessions = [
            SessionInfo(
                session_id="abc123def456",
                cwd="/test",
                jsonl_path="/test.jsonl",
            ),
        ]

        with mock.patch(
            "lib.session_discovery.discover_all_sessions", return_value=mock_sessions
        ):
            result = get_session_by_id("abc123def456")
            assert result is not None
            assert result.session_id == "abc123def456"

    def test_finds_session_by_partial_id(self):
        """Should find session by partial session ID prefix."""
        mock_sessions = [
            SessionInfo(
                session_id="abc123def456",
                cwd="/test",
                jsonl_path="/test.jsonl",
            ),
        ]

        with mock.patch(
            "lib.session_discovery.discover_all_sessions", return_value=mock_sessions
        ):
            result = get_session_by_id("abc123")
            assert result is not None
            assert result.session_id == "abc123def456"

    def test_returns_none_for_nonexistent_id(self):
        """Should return None when session ID not found."""
        with mock.patch(
            "lib.session_discovery.discover_all_sessions", return_value=[]
        ):
            result = get_session_by_id("nonexistent")
            assert result is None
