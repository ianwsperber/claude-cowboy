"""Tests for status_analyzer module."""

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from lib.status_analyzer import (
    HookState,
    SessionStatus,
    StatusResult,
    analyze_pane_status,
    analyze_session_status,
    get_display_status,
    get_hook_status_dir,
    get_session_status,
    get_status_emoji,
    get_wait_dir,
    read_hook_state,
)


class TestSessionStatus:
    """Tests for SessionStatus enum."""

    def test_has_expected_values(self):
        """Should have all expected status values."""
        assert SessionStatus.WORKING.value == "working"
        assert SessionStatus.DONE.value == "done"
        assert SessionStatus.WAIT.value == "wait"
        assert SessionStatus.NEEDS_INPUT.value == "needs input"
        assert SessionStatus.UNKNOWN.value == "unknown"


class TestGetSessionStatus:
    """Tests for get_session_status function."""

    def test_returns_unknown_for_empty_session_id(self):
        """Should return UNKNOWN for empty session ID."""
        status, suffix = get_session_status("")
        assert status == SessionStatus.UNKNOWN
        assert suffix == ""

    def test_returns_unknown_when_no_status_file(self):
        """Should return UNKNOWN when status file doesn't exist."""
        status, suffix = get_session_status("nonexistent-session-id")
        assert status == SessionStatus.UNKNOWN

    def test_reads_working_status(self):
        """Should read 'working' status from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_dir = Path(tmpdir) / "status"
            status_dir.mkdir()
            status_file = status_dir / "test-session.status"
            status_file.write_text("working")

            with mock.patch(
                "lib.status_analyzer.get_hook_status_dir", return_value=status_dir
            ):
                with mock.patch(
                    "lib.status_analyzer.get_wait_dir",
                    return_value=Path(tmpdir) / "wait",
                ):
                    status, suffix = get_session_status("test-session")
                    assert status == SessionStatus.WORKING
                    assert suffix == ""

    def test_reads_done_status(self):
        """Should read 'done' status from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_dir = Path(tmpdir) / "status"
            status_dir.mkdir()
            status_file = status_dir / "test-session.status"
            status_file.write_text("done")

            with mock.patch(
                "lib.status_analyzer.get_hook_status_dir", return_value=status_dir
            ):
                with mock.patch(
                    "lib.status_analyzer.get_wait_dir",
                    return_value=Path(tmpdir) / "wait",
                ):
                    status, suffix = get_session_status("test-session")
                    assert status == SessionStatus.DONE

    def test_wait_timer_takes_precedence(self):
        """Wait timer should take precedence over status file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_dir = Path(tmpdir) / "status"
            status_dir.mkdir()
            status_file = status_dir / "test-session.status"
            status_file.write_text("working")

            wait_dir = Path(tmpdir) / "wait"
            wait_dir.mkdir()
            wait_file = wait_dir / "test-session.wait"
            # Set expiry 5 minutes in the future
            wait_file.write_text(str(int(time.time()) + 300))

            with mock.patch(
                "lib.status_analyzer.get_hook_status_dir", return_value=status_dir
            ):
                with mock.patch(
                    "lib.status_analyzer.get_wait_dir", return_value=wait_dir
                ):
                    status, suffix = get_session_status("test-session")
                    assert status == SessionStatus.WAIT
                    assert "m)" in suffix  # Should show minutes remaining


class TestHookState:
    """Tests for HookState dataclass."""

    def test_is_stale_returns_true_for_missing_timestamp(self):
        """Should be stale if no timestamp."""
        state = HookState(session_id="test", state="working", tool="Bash")
        assert state.is_stale is True

    def test_is_stale_returns_true_for_old_timestamp(self):
        """Should be stale if timestamp is > 5 minutes old."""
        old_time = datetime.now(timezone.utc).replace(microsecond=0)
        old_time = old_time.isoformat()  # This will be interpreted as now, so we need to mock
        state = HookState(
            session_id="test",
            state="working",
            tool="Bash",
            timestamp="2020-01-01T00:00:00+00:00",
        )
        assert state.is_stale is True

    def test_is_stale_returns_false_for_recent_timestamp(self):
        """Should not be stale if timestamp is recent."""
        recent_time = datetime.now(timezone.utc).isoformat()
        state = HookState(
            session_id="test",
            state="working",
            tool="Bash",
            timestamp=recent_time,
        )
        assert state.is_stale is False


class TestAnalyzePaneStatus:
    """Tests for analyze_pane_status function."""

    def test_returns_unknown_for_empty_content(self):
        """Should return UNKNOWN for empty/None content."""
        result = analyze_pane_status(None)
        assert result.status == SessionStatus.UNKNOWN
        assert result.is_plan_mode is False

    def test_detects_plan_mode(self):
        """Should detect plan mode from pane content."""
        result = analyze_pane_status("Some text plan mode on more text")
        assert result.is_plan_mode is True

    def test_detects_waiting_for_input(self):
        """Should detect waiting for input prompt."""
        result = analyze_pane_status("Do you want to proceed?")
        assert result.status == SessionStatus.NEEDS_INPUT


class TestAnalyzeSessionStatus:
    """Tests for analyze_session_status function."""

    def test_extracts_session_id_from_path(self):
        """Should extract session ID from JSONL path."""
        with mock.patch(
            "lib.status_analyzer.get_session_status",
            return_value=(SessionStatus.WORKING, ""),
        ):
            result = analyze_session_status(
                pid=None, jsonl_path="/path/to/abc123.jsonl"
            )
            assert result.status == SessionStatus.WORKING

    def test_uses_provided_session_id(self):
        """Should use provided session_id if given."""
        with mock.patch(
            "lib.status_analyzer.get_session_status",
            return_value=(SessionStatus.DONE, ""),
        ) as mock_get_status:
            analyze_session_status(
                pid=1234, jsonl_path=None, session_id="my-session"
            )
            mock_get_status.assert_called_with("my-session")


class TestGetStatusEmoji:
    """Tests for get_status_emoji function."""

    def test_returns_correct_emojis(self):
        """Should return correct emoji for each status."""
        assert get_status_emoji(SessionStatus.WORKING) == "⚡"
        assert get_status_emoji(SessionStatus.DONE) == "✓"
        assert get_status_emoji(SessionStatus.WAIT) == "⏳"
        assert get_status_emoji(SessionStatus.UNKNOWN) == "❓"


class TestGetDisplayStatus:
    """Tests for get_display_status function."""

    def test_working_status(self):
        """Should return Working display for working status."""
        result = StatusResult(status=SessionStatus.WORKING, reason="test")
        display = get_display_status(result)
        assert display.label == "Working"
        assert display.emoji == "⚡"

    def test_done_status(self):
        """Should return Done display for done status."""
        result = StatusResult(status=SessionStatus.DONE, reason="test")
        display = get_display_status(result)
        assert display.label == "Done"
        assert display.emoji == "✓"

    def test_wait_status_with_suffix(self):
        """Should include suffix in wait status label."""
        result = StatusResult(status=SessionStatus.WAIT, reason="test")
        display = get_display_status(result, suffix=" (5m)")
        assert display.label == "Wait (5m)"

    def test_plan_mode_display(self):
        """Should show Plan Mode for unknown status with plan mode."""
        result = StatusResult(
            status=SessionStatus.UNKNOWN, reason="test", is_plan_mode=True
        )
        display = get_display_status(result)
        assert "Plan" in display.label
