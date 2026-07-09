"""Tests for the HTML report renderer, focused on outcome badges."""

from qirabot.report import write_html


def _entry(section, **over):
    e = {
        "section": section,
        "action_type": "click",
        "params": {"locate": "button"},
        "decision": "",
        "output": "",
        "finished": False,
        "success": True,
        "coords": None,
        "screenshot": "",
        "thumb": "",
    }
    e.update(over)
    return e


class TestSectionBadges:
    def test_four_statuses_render_distinct_badges(self, tmp_path):
        log = [_entry(s) for s in ("a", "b", "c", "d")]
        out = write_html(
            log,
            tmp_path / "report.html",
            outcomes={
                "a": "completed",
                "b": "goal_failed",
                "c": "max_steps",
                "d": "error",
            },
        )
        html = out.read_text(encoding="utf-8")
        assert '<span class="badge pass">a: PASS</span>' in html
        assert '<span class="badge fail">b: FAIL</span>' in html
        assert '<span class="badge warn">c: MAX STEPS</span>' in html
        assert '<span class="badge fail">d: ERROR</span>' in html

    def test_legacy_bool_outcomes_still_render(self, tmp_path):
        # Pre-status callers passed dict[str, bool]; True/False must keep
        # rendering as PASS/FAIL.
        log = [_entry("a"), _entry("b")]
        out = write_html(
            log, tmp_path / "report.html", outcomes={"a": True, "b": False}
        )
        html = out.read_text(encoding="utf-8")
        assert "a: PASS" in html
        assert "b: FAIL" in html

    def test_unknown_status_falls_back_to_fail(self, tmp_path):
        out = write_html(
            [_entry("a")], tmp_path / "report.html", outcomes={"a": "someday-new"}
        )
        assert "a: FAIL" in out.read_text(encoding="utf-8")

    def test_unjudged_section_stays_neutral(self, tmp_path):
        out = write_html([_entry("setup")], tmp_path / "report.html", outcomes={})
        assert "badge neutral" in out.read_text(encoding="utf-8")


class TestSummaryBadge:
    def test_all_completed_is_green(self, tmp_path):
        out = write_html(
            [_entry("a")], tmp_path / "report.html", outcomes={"a": "completed"}
        )
        assert '<span class="badge pass">1/1 passed</span>' in out.read_text(
            encoding="utf-8"
        )

    def test_only_truncation_is_amber(self, tmp_path):
        log = [_entry("a"), _entry("b")]
        out = write_html(
            log,
            tmp_path / "report.html",
            outcomes={"a": "completed", "b": "max_steps"},
        )
        assert (
            '<span class="badge warn">1/2 passed · 1 truncated</span>'
            in out.read_text(encoding="utf-8")
        )

    def test_any_real_failure_is_red(self, tmp_path):
        log = [_entry("a"), _entry("b"), _entry("c")]
        out = write_html(
            log,
            tmp_path / "report.html",
            outcomes={"a": "completed", "b": "max_steps", "c": "goal_failed"},
        )
        assert (
            '<span class="badge fail">1/3 passed · 1 truncated</span>'
            in out.read_text(encoding="utf-8")
        )


class TestWarnRow:
    def test_warn_entry_renders_amber_not_red(self, tmp_path):
        log = [
            _entry(
                "a",
                action_type="ai",
                output="max steps reached",
                finished=True,
                success=False,
                warn=True,
            )
        ]
        out = write_html(log, tmp_path / "report.html", outcomes={"a": "max_steps"})
        html = out.read_text(encoding="utf-8")
        # Row classes appear in the body as class='act warn-row' etc.; the
        # stylesheet always mentions fail-row, so match the attribute form.
        assert "'act warn-row'" in html
        assert "'act fail-row'" not in html
        assert "ai ⚠" in html

    def test_failed_entry_still_renders_red(self, tmp_path):
        log = [_entry("a", success=False, output="boom")]
        out = write_html(log, tmp_path / "report.html", outcomes={"a": "error"})
        html = out.read_text(encoding="utf-8")
        assert "'act fail-row'" in html
        assert "✗" in html


class TestStepTimestamps:
    def test_offsets_relative_to_first_step_without_recording(self, tmp_path):
        log = [_entry("a", ts=1000.0), _entry("a", ts=1092.0)]
        out = write_html(log, tmp_path / "report.html")
        html = out.read_text(encoding="utf-8")
        assert "+0:00" in html
        assert "+1:32" in html
        # No video on the page → offsets are plain text, not seek links.
        assert "seekTo" not in html

    def test_offsets_seek_video_when_recording_start_known(self, tmp_path):
        log = [_entry("a", ts=1005.5)]
        out = write_html(
            log,
            tmp_path / "report.html",
            recording="recording.mp4",
            recording_start=1000.0,
        )
        html = out.read_text(encoding="utf-8")
        assert "seekTo(5.5)" in html
        assert "+0:05" in html

    def test_recording_without_start_ts_stays_unlinked(self, tmp_path):
        # Recording present but its start time unknown (e.g. an external
        # recording.mp4 dropped into report_dir): offsets fall back to
        # run-relative plain text; only the video player's own script exists.
        log = [_entry("a", ts=1000.0), _entry("a", ts=1007.0)]
        out = write_html(log, tmp_path / "report.html", recording="recording.mp4")
        html = out.read_text(encoding="utf-8")
        assert "+0:07" in html
        assert "onclick='return seekTo" not in html

    def test_entries_without_ts_render_blank_time_cell(self, tmp_path):
        # Logs from before the ts field (or external write_html callers) must
        # still render — time cells just stay empty.
        out = write_html([_entry("a")], tmp_path / "report.html")
        html = out.read_text(encoding="utf-8")
        assert ">time<" in html
        assert "seekTo" not in html


class TestSectionErrorBanners:
    def test_max_steps_banner_renders_amber(self, tmp_path):
        out = write_html(
            [_entry("a")],
            tmp_path / "report.html",
            outcomes={"a": "max_steps"},
            section_errors={"a": "max steps reached (5)"},
        )
        html = out.read_text(encoding="utf-8")
        assert "max steps reached (5)" in html
        assert "<div class='notice'>⚠ max steps reached (5)</div>" in html

    def test_error_banner_renders_red(self, tmp_path):
        out = write_html(
            [_entry("a")],
            tmp_path / "report.html",
            outcomes={"a": "error"},
            section_errors={"a": "session expired"},
        )
        html = out.read_text(encoding="utf-8")
        assert "<div class='notice error'>✗ session expired</div>" in html

    def test_error_only_section_still_renders(self, tmp_path):
        # A section that failed before recording any step must still show its
        # banner (and badge) — otherwise the failure reason vanishes.
        out = write_html(
            [_entry("a")],
            tmp_path / "report.html",
            outcomes={"a": "completed", "b": "error"},
            section_errors={"b": "AI request failed"},
        )
        html = out.read_text(encoding="utf-8")
        assert "AI request failed" in html
        assert "b:" in html  # badge line for the error-only section


class TestStatsLine:
    def test_total_steps_headline_with_ai_subset(self, tmp_path):
        out = write_html(
            [_entry("a"), _entry("a"), _entry("a")],
            tmp_path / "report.html",
            stats={"total_steps": 3, "ai_steps": 2, "input_tokens": 1000,
                   "output_tokens": 500, "thinking_tokens": 0,
                   "step_duration_ms": 1200},
        )
        html = out.read_text(encoding="utf-8")
        assert "3 steps (2 AI)" in html

    def test_pure_local_run_still_renders_stats(self, tmp_path):
        # 0 AI steps used to suppress the stats line entirely; a purely local
        # script still deserves its step count.
        out = write_html(
            [_entry("setup"), _entry("setup")],
            tmp_path / "report.html",
            stats={"total_steps": 2, "ai_steps": 0},
        )
        html = out.read_text(encoding="utf-8")
        assert "2 steps (0 AI)" in html

    def test_legacy_stats_without_total_steps_fall_back_to_log_length(self, tmp_path):
        out = write_html(
            [_entry("a")],
            tmp_path / "report.html",
            stats={"ai_steps": 1},
        )
        html = out.read_text(encoding="utf-8")
        assert "1 steps (1 AI)" in html
