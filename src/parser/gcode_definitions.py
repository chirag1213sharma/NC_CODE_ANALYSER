"""
NC Code Analyser - G-Code and M-Code Definitions
"""

# Standard G-Codes (ISO 6983 / RS274)
G_CODES = {
    # Motion Commands
    "G00": {"name": "Rapid Positioning", "category": "motion", "modal_group": 1},
    "G01": {"name": "Linear Interpolation", "category": "motion", "modal_group": 1},
    "G02": {"name": "Circular Interpolation CW", "category": "motion", "modal_group": 1},
    "G03": {"name": "Circular Interpolation CCW", "category": "motion", "modal_group": 1},
    "G04": {"name": "Dwell", "category": "motion", "modal_group": 0},
    
    # Plane Selection
    "G17": {"name": "XY Plane", "category": "plane", "modal_group": 2},
    "G18": {"name": "XZ Plane", "category": "plane", "modal_group": 2},
    "G19": {"name": "YZ Plane", "category": "plane", "modal_group": 2},
    
    # Units
    "G20": {"name": "Inch Mode", "category": "units", "modal_group": 6},
    "G21": {"name": "Metric Mode", "category": "units", "modal_group": 6},
    
    # Coordinate Modes
    "G90": {"name": "Absolute Positioning", "category": "positioning", "modal_group": 3},
    "G91": {"name": "Incremental Positioning", "category": "positioning", "modal_group": 3},
    
    # Work Offsets
    "G54": {"name": "Work Offset 1", "category": "work_offset", "modal_group": 12},
    "G55": {"name": "Work Offset 2", "category": "work_offset", "modal_group": 12},
    "G56": {"name": "Work Offset 3", "category": "work_offset", "modal_group": 12},
    "G57": {"name": "Work Offset 4", "category": "work_offset", "modal_group": 12},
    "G58": {"name": "Work Offset 5", "category": "work_offset", "modal_group": 12},
    "G59": {"name": "Work Offset 6", "category": "work_offset", "modal_group": 12},
    
    # Canned Cycles
    "G80": {"name": "Cancel Canned Cycle", "category": "canned_cycle", "modal_group": 9},
    "G81": {"name": "Drill Cycle", "category": "canned_cycle", "modal_group": 9},
    "G82": {"name": "Drill Cycle with Dwell", "category": "canned_cycle", "modal_group": 9},
    "G83": {"name": "Peck Drill Cycle", "category": "canned_cycle", "modal_group": 9},
    "G84": {"name": "Tapping Cycle", "category": "canned_cycle", "modal_group": 9},
    "G85": {"name": "Boring Cycle", "category": "canned_cycle", "modal_group": 9},
    "G86": {"name": "Boring Cycle", "category": "canned_cycle", "modal_group": 9},
    "G87": {"name": "Back Boring Cycle", "category": "canned_cycle", "modal_group": 9},
    "G88": {"name": "Boring Cycle", "category": "canned_cycle", "modal_group": 9},
    "G89": {"name": "Boring Cycle", "category": "canned_cycle", "modal_group": 9},
    
    # Tool Compensation
    "G40": {"name": "Cancel Cutter Compensation", "category": "cutter_comp", "modal_group": 7},
    "G41": {"name": "Cutter Compensation Left", "category": "cutter_comp", "modal_group": 7},
    "G42": {"name": "Cutter Compensation Right", "category": "cutter_comp", "modal_group": 7},
    "G43": {"name": "Tool Length Offset +", "category": "tool_length", "modal_group": 8},
    "G44": {"name": "Tool Length Offset -", "category": "tool_length", "modal_group": 8},
    "G49": {"name": "Cancel Tool Length Offset", "category": "tool_length", "modal_group": 8},
    
    # Return Modes
    "G98": {"name": "Return to Initial Level", "category": "return_mode", "modal_group": 10},
    "G99": {"name": "Return to R Level", "category": "return_mode", "modal_group": 10},
    
    # Turning Specific
    "G70": {"name": "Finishing Cycle", "category": "turning", "modal_group": 0},
    "G71": {"name": "Rough Turning Cycle", "category": "turning", "modal_group": 0},
    "G72": {"name": "Rough Facing Cycle", "category": "turning", "modal_group": 0},
    "G73": {"name": "Pattern Repeat Cycle", "category": "turning", "modal_group": 0},
    "G74": {"name": "Peck Drilling Cycle (Lathe)", "category": "turning", "modal_group": 0},
    "G75": {"name": "Grooving Cycle", "category": "turning", "modal_group": 0},
    "G76": {"name": "Threading Cycle", "category": "turning", "modal_group": 0},
    
    # Multi-axis
    "G68": {"name": "Coordinate Rotation", "category": "multiaxis", "modal_group": 16},
    "G69": {"name": "Cancel Coordinate Rotation", "category": "multiaxis", "modal_group": 16},
    "G68.2": {"name": "Tilted Work Plane", "category": "multiaxis", "modal_group": 16},
}

# Standard M-Codes
M_CODES = {
    # Program Control
    "M00": {"name": "Program Stop", "category": "program_control"},
    "M01": {"name": "Optional Stop", "category": "program_control"},
    "M02": {"name": "Program End", "category": "program_control"},
    "M30": {"name": "Program End and Reset", "category": "program_control"},
    
    # Spindle Control
    "M03": {"name": "Spindle On CW", "category": "spindle"},
    "M04": {"name": "Spindle On CCW", "category": "spindle"},
    "M05": {"name": "Spindle Stop", "category": "spindle"},
    "M19": {"name": "Spindle Orient", "category": "spindle"},
    
    # Coolant Control
    "M07": {"name": "Mist Coolant On", "category": "coolant"},
    "M08": {"name": "Flood Coolant On", "category": "coolant"},
    "M09": {"name": "Coolant Off", "category": "coolant"},
    
    # Tool Change
    "M06": {"name": "Tool Change", "category": "tool"},
    
    # Subprogram
    "M97": {"name": "Local Subprogram Call", "category": "subprogram"},
    "M98": {"name": "Subprogram Call", "category": "subprogram"},
    "M99": {"name": "Subprogram Return", "category": "subprogram"},
    
    # Chuck/Clamp (Lathe)
    "M10": {"name": "Chuck Clamp", "category": "clamp"},
    "M11": {"name": "Chuck Unclamp", "category": "clamp"},
    
    # Tailstock (Lathe)
    "M21": {"name": "Tailstock Forward", "category": "tailstock"},
    "M22": {"name": "Tailstock Retract", "category": "tailstock"},
}

# Address Letters and their meanings
ADDRESS_LETTERS = {
    "A": "A-axis rotary position",
    "B": "B-axis rotary position",
    "C": "C-axis rotary position",
    "D": "Tool diameter offset number",
    "E": "Precision feedrate (turning)",
    "F": "Feedrate",
    "G": "G-code command",
    "H": "Tool length offset number",
    "I": "Arc center X offset / Thread lead",
    "J": "Arc center Y offset",
    "K": "Arc center Z offset",
    "L": "Loop count / Fixed cycle",
    "M": "M-code command",
    "N": "Block/Line number",
    "O": "Program number",
    "P": "Dwell time / Parameter",
    "Q": "Peck increment / Shift",
    "R": "Arc radius / Retract level",
    "S": "Spindle speed",
    "T": "Tool number",
    "U": "Incremental X (lathe) / Secondary X",
    "V": "Secondary Y",
    "W": "Incremental Z (lathe) / Secondary Z",
    "X": "X-axis position",
    "Y": "Y-axis position",
    "Z": "Z-axis position",
}

# Critical G-codes that affect machine behavior significantly
CRITICAL_G_CODES = {"G00", "G01", "G02", "G03", "G20", "G21", "G40", "G41", "G42", "G43", "G90", "G91"}

# Critical M-codes that affect machine state
CRITICAL_M_CODES = {"M03", "M04", "M05", "M06", "M08", "M09", "M30"}


def get_gcode_info(code: str) -> dict:
    """Get information about a G-code."""
    # Normalize code format (G1 -> G01)
    normalized = code.upper()
    if len(normalized) == 2:  # e.g., G1 -> G01
        normalized = f"{normalized[0]}0{normalized[1]}"
    return G_CODES.get(normalized, {"name": "Unknown", "category": "unknown", "modal_group": -1})


def get_mcode_info(code: str) -> dict:
    """Get information about an M-code."""
    # Normalize code format (M3 -> M03)
    normalized = code.upper()
    if len(normalized) == 2:  # e.g., M3 -> M03
        normalized = f"{normalized[0]}0{normalized[1]}"
    return M_CODES.get(normalized, {"name": "Unknown", "category": "unknown"})


def is_critical_change(g_codes: list, m_codes: list) -> bool:
    """Check if any of the codes are critical for machine operation."""
    for code in g_codes:
        normalized = code.upper()
        if len(normalized) == 2:
            normalized = f"{normalized[0]}0{normalized[1]}"
        if normalized in CRITICAL_G_CODES:
            return True
    
    for code in m_codes:
        normalized = code.upper()
        if len(normalized) == 2:
            normalized = f"{normalized[0]}0{normalized[1]}"
        if normalized in CRITICAL_M_CODES:
            return True
    
    return False
