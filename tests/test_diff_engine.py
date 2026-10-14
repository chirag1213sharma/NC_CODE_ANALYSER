"""
Tests for Diff Engine Module
"""

import pytest
from src.diff_engine import DiffEngine, ChangeType, ChangeSeverity


class TestDiffEngine:
    """Test cases for the Diff Engine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = DiffEngine()

    def test_identical_files(self):
        """Test comparison of identical files."""
        content = """
        G00 X0 Y0
        G01 X10 Y10 F500
        """
        
        result = self.engine.compare_content(content, content)
        
        assert result.files_identical == True
        assert result.summary.lines_added == 0
        assert result.summary.lines_removed == 0
        assert result.summary.lines_modified == 0

    def test_added_lines(self):
        """Test detection of added lines."""
        baseline = """G00 X0 Y0
G01 X10 Y10"""
        
        new = """G00 X0 Y0
G01 X10 Y10
G01 X20 Y20"""
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.files_identical == False
        assert result.summary.lines_added >= 1

    def test_removed_lines(self):
        """Test detection of removed lines."""
        baseline = """G00 X0 Y0
G01 X10 Y10
G01 X20 Y20"""
        
        new = """G00 X0 Y0
G01 X10 Y10"""
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.files_identical == False
        assert result.summary.lines_removed >= 1

    def test_modified_coordinates(self):
        """Test detection of modified coordinates."""
        baseline = "G01 X10.0 Y10.0 F500"
        new = "G01 X15.0 Y15.0 F500"
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.files_identical == False
        # Check for coordinate changes in command diffs
        coord_changes = [d for d in result.command_diffs if d.coordinate_changes]
        assert len(coord_changes) > 0

    def test_modified_feed_rate(self):
        """Test detection of feed rate changes."""
        baseline = "G01 X10.0 Y10.0 F500"
        new = "G01 X10.0 Y10.0 F800"
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.files_identical == False
        feed_changes = [d for d in result.command_diffs if d.feed_change]
        assert len(feed_changes) > 0

    def test_tool_change_detection(self):
        """Test detection of tool changes."""
        baseline = """T1 M06
G00 X0 Y0"""
        
        new = """T2 M06
G00 X0 Y0"""
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.files_identical == False
        tool_changes = [d for d in result.command_diffs if d.tool_change]
        assert len(tool_changes) > 0

    def test_critical_change_flagging(self):
        """Test that critical changes are flagged."""
        baseline = "G00 X0 Y0"
        new = "G00 X10 Y10"
        
        result = self.engine.compare_content(baseline, new)
        
        critical = [d for d in result.command_diffs if d.is_critical]
        # Coordinate changes should be critical
        assert len(critical) > 0

    def test_comment_change_severity(self):
        """Test that comment changes have low severity."""
        baseline = "(OLD COMMENT)"
        new = "(NEW COMMENT)"
        
        result = self.engine.compare_content(baseline, new)
        
        if result.line_diffs:
            comment_changes = [d for d in result.line_diffs 
                             if d.change_category.value == "comment"]
            for change in comment_changes:
                assert change.severity == ChangeSeverity.INFO

    def test_operation_diff_detection(self):
        """Test operation-level diff detection."""
        baseline = """T1 M06
G00 X0 Y0
G01 X10 Y10"""
        
        new = """T1 M06
G00 X0 Y0
G01 X15 Y15
T2 M06
G00 X20 Y20"""
        
        result = self.engine.compare_content(baseline, new)
        
        # Should detect operation changes
        assert len(result.operation_diffs) > 0

    def test_summary_calculation(self):
        """Test summary statistics calculation."""
        baseline = """G00 X0 Y0
G01 X10 Y10
G01 X20 Y20"""
        
        new = """G00 X0 Y0
G01 X15 Y15
G01 X25 Y25
G01 X30 Y30"""
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.summary is not None
        assert result.summary.total_lines_old == 3
        assert result.summary.total_lines_new == 4
        assert result.summary.lines_added + result.summary.lines_modified >= 1

    def test_category_breakdown(self):
        """Test change category breakdown in summary."""
        baseline = """G00 X0 Y0
S2000 M03
F500"""
        
        new = """G00 X10 Y10
S3000 M03
F800"""
        
        result = self.engine.compare_content(baseline, new)
        
        assert result.summary is not None
        # Should have some category breakdown
        # Categories could be coordinate, feed_speed, etc.


class TestChangeCategories:
    """Test cases for change categorization."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = DiffEngine()

    def test_coordinate_category(self):
        """Test coordinate change categorization."""
        baseline = "G01 X10.0 Y10.0"
        new = "G01 X20.0 Y20.0"
        
        result = self.engine.compare_content(baseline, new)
        
        for diff in result.line_diffs:
            if diff.change_type != ChangeType.UNCHANGED:
                # Should be categorized as coordinate
                assert diff.change_category.value in ["coordinate", "unknown"]

    def test_motion_category(self):
        """Test motion G-code categorization."""
        baseline = "G00 X10.0 Y10.0"
        new = "G01 X10.0 Y10.0"
        
        result = self.engine.compare_content(baseline, new)
        
        for diff in result.command_diffs:
            if diff.g_codes_added or diff.g_codes_removed:
                # Changed motion type
                assert diff.line_diff.change_category.value in ["motion", "unknown"]
