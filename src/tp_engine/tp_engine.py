import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import re

def plot_gcode(file_content):
    lines = file_content.split('\n')
    
    # Store coordinates
    x_rapids, y_rapids, z_rapids = [], [], []
    x_feeds, y_feeds, z_feeds = [], [], []
    
    current_x = 0
    current_y = 0
    current_z = 0
    
    is_rapid = False # Track if current mode is G00
    
    for line in lines:
        # Simple parsing for G00, G01, X, Y, Z
        if 'G00' in line:
            is_rapid = True
        if 'G01' in line or 'G02' in line or 'G03' in line:
            is_rapid = False
            
        # Extract X, Y, Z coordinates
        x_match = re.search(r'X([-\d\.]+)', line)
        y_match = re.search(r'Y([-\d\.]+)', line)
        z_match = re.search(r'Z([-\d\.]+)', line)
        
        if x_match: current_x = float(x_match.group(1))
        if y_match: current_y = float(y_match.group(1))
        if z_match: current_z = float(z_match.group(1))
        
        # Determine where to store the point based on move type
        if is_rapid:
            x_rapids.append(current_x)
            y_rapids.append(current_y)
            z_rapids.append(current_z)
            # Add None to break lines between discontinuous rapids if needed, 
            # but for simple scatter/line plot we keep continuous for now 
            # or separate segments. Here we just plot points for context.
        else:
            x_feeds.append(current_x)
            y_feeds.append(current_y)
            z_feeds.append(current_z)

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection='3d')

    # Plot Feed moves (Blue - Cutting)
    ax.plot(x_feeds, y_feeds, z_feeds, label='Feed (Cut)', color='blue', linewidth=1)
    
    # Plot Rapid moves (Red - Air)
    ax.scatter(x_rapids, y_rapids, z_rapids, label='Rapid (G00)', color='red', s=5)

    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_zlabel('Z (mm)')
    ax.set_title('Toolpath Visualization (CW-110525)')
    ax.legend()
    
    plt.show()


if __name__ == "__main__":
    gcode = """
        N1 ( AUSSENKONTUR SCHRUPPEN _1 )
        N2 (SCHRUPPSTAHL W-PLATTE R0,8)
        N3 T0606
        N4 B90.
        N5 M303 (Main Spindle Select)
        N6 G99 G96 S200 M04
        N7 M08
        N8 G54 G00 X100. Z5.
        N9 Z1.
        N10 X80.
        N11 G71 U3. R1.
        N12 G71 P13 Q16 U.8 W.1 F.2
        N13 X74.53
        N14 G01 Z-.23 F.2
        N15 X77. Z-1.47
        N16 Z-58.3
        N17 G00 X182. M09
        N18 Z-52.5
        N19 M05
        N20 M30
    """
    plot_gcode(gcode)