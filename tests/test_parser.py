"""
Tests for NC Parser Module
"""

import pytest
from pathlib import Path

from src.parser import NCParser, NCProgram, MachineType, UnitSystem


class TestNCParser:
    """Test cases for the NC Parser."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = NCParser()

    def test_parse_simple_program(self):
        """Test parsing a simple NC program."""
        content = """
        %
        O0001 (TEST PROGRAM)
        N10 G90 G21
        N20 G54
        N30 T1 M06
        N40 S2000 M03
        N50 G00 X0 Y0
        N60 G43 H1 Z50.0
        N70 G01 Z-5.0 F200.0
        N80 M05
        N90 M30
        %
        """
        
        result = self.parser.parse_content(content, "test.nc")
        
        assert result.success
        assert result.program is not None
        assert result.program.program_number == "0001"
        assert result.program.unit_system == UnitSystem.METRIC
        assert len(result.program.tools_used) == 1
        assert result.program.tools_used[0].tool_number == 1

    def test_parse_g_codes(self):
        """Test G-code extraction."""
        content = "G00 G90 G17 X10.0 Y20.0"
        
        result = self.parser.parse_content(content)
        
        assert result.success
        assert result.program is not None
        commands = result.program.all_commands
        assert len(commands) == 1
        assert "G00" in commands[0].g_codes or "G0" in commands[0].g_codes
        assert "G90" in commands[0].g_codes
        assert "G17" in commands[0].g_codes

    def test_parse_coordinates(self):
        """Test coordinate extraction."""
        content = "G01 X100.5 Y-50.25 Z10.0 F500"
        
        result = self.parser.parse_content(content)
        
        assert result.success
        cmd = result.program.all_commands[0]
        assert cmd.coordinates is not None
        assert cmd.coordinates.x == 100.5
        assert cmd.coordinates.y == -50.25
        assert cmd.coordinates.z == 10.0
        assert cmd.feed_rate == 500.0

    def test_parse_tool_change(self):
        """Test tool change detection."""
        content = """
        T1 M06 (TOOL 1 - END MILL)
        S3000 M03
        T2 M06 (TOOL 2 - DRILL)
        S2000 M03
        """
        
        result = self.parser.parse_content(content)
        
        assert result.success
        assert len(result.program.tools_used) == 2
        assert result.program.tools_used[0].tool_number == 1
        assert result.program.tools_used[1].tool_number == 2

    def test_parse_comments(self):
        """Test comment extraction."""
        content = "(THIS IS A COMMENT) G00 X0 Y0"
        
        result = self.parser.parse_content(content)
        
        assert result.success
        cmd = result.program.all_commands[0]
        assert cmd.comment == "THIS IS A COMMENT"

    def test_parse_operations(self):
        """Test operation detection."""
        content = """
        (OPERATION 1: FACING)
        T1 M06
        G00 X0 Y0
        (OPERATION 2: ROUGHING)
        T2 M06
        G00 X10 Y10
        """
        
        result = self.parser.parse_content(content)
        
        assert result.success
        assert result.program.total_operations >= 2

    def test_detect_machine_type_mill(self):
        """Test mill machine type detection."""
        content = """
        G00 X10.0 Y20.0 Z5.0
        G01 X50.0 Y50.0 F500
        """
        
        result = self.parser.parse_content(content)
        
        assert result.success
        assert result.program.machine_type == MachineType.MILL

    def test_detect_machine_type_multiaxis(self):
        """Test multi-axis machine detection."""
        content = """
        G00 X10.0 Y20.0 Z5.0 A45.0 B30.0
        G01 X50.0 Y50.0 C90.0 F500
        """
        
        result = self.parser.parse_content(content)
        
        assert result.success
        assert result.program.machine_type == MachineType.MULTIAXIS

    def test_parse_arc(self):
        """Test arc interpolation parsing."""
        content = "G02 X50.0 Y50.0 I25.0 J0.0 F300"
        
        result = self.parser.parse_content(content)
        
        assert result.success
        cmd = result.program.all_commands[0]
        assert "G02" in cmd.g_codes or "G2" in cmd.g_codes
        assert cmd.coordinates.i == 25.0
        assert cmd.coordinates.j == 0.0

    def test_parse_spindle_speed(self):
        """Test spindle speed extraction."""
        content = "S5000 M03"
        
        result = self.parser.parse_content(content)
        
        assert result.success
        cmd = result.program.all_commands[0]
        assert cmd.spindle_speed == 5000.0
        assert "M03" in cmd.m_codes or "M3" in cmd.m_codes

    def test_parse_sample_file(self):
        """Test parsing a sample file if it exists."""
        sample_path = Path(__file__).parent.parent / "samples" / "baseline_sample.nc"
        
        if sample_path.exists():
            result = self.parser.parse_file(str(sample_path))
            
            assert result.success
            assert result.program is not None
            assert result.program.total_lines > 0
            assert result.program.total_operations > 0
            assert result.program.total_tools > 0


class TestGCodeDefinitions:
    """Test cases for G-code definitions."""

    def test_get_gcode_info(self):
        """Test G-code info retrieval."""
        from src.parser.gcode_definitions import get_gcode_info
        
        info = get_gcode_info("G00")
        assert info["name"] == "Rapid Positioning"
        assert info["category"] == "motion"

        info = get_gcode_info("G1")  # Short form
        assert info["name"] == "Linear Interpolation"

    def test_get_mcode_info(self):
        """Test M-code info retrieval."""
        from src.parser.gcode_definitions import get_mcode_info
        
        info = get_mcode_info("M03")
        assert info["name"] == "Spindle On CW"
        assert info["category"] == "spindle"

    def test_is_critical_change(self):
        """Test critical change detection."""
        from src.parser.gcode_definitions import is_critical_change
        
        assert is_critical_change(["G00"], []) == True
        assert is_critical_change(["G17"], []) == False
        assert is_critical_change([], ["M03"]) == True
        assert is_critical_change([], ["M07"]) == False
