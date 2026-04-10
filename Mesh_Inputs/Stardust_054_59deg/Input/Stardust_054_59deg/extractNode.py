import gmsh
import math
import numpy as np
import matplotlib.pyplot as plt

# Functions
def extractNodes(elementType, tag_Num):

    # Get coordinate of the surface
    node_tag, coord, para_coord = gmsh.model.mesh.getNodesByElementType(elementType, tag_Num, returnParametricCoord=True)

    # Initialize data extraction
    nodetag_array = []
    x_array = []
    y_array = []
    z_array = []
    i = 0
    seen = {} # empty dictionary

    # Extract x, y, z, and node tag
    for tag in node_tag:
        nodetag = tag
        x = coord[i * 3]
        y = coord[i * 3 + 1]
        z = coord[i * 3 + 2]

        if tag not in seen:
            seen[nodetag] = (x, y, z)
            nodetag_array.append(tag)
            x_array.append(x)
            y_array.append(y)
            z_array.append(z)
        i = i + 1

    return nodetag_array, x_array, y_array, z_array

# Initialize
gmsh.initialize()

# Open mesh file
gmsh.open("Stardust_054_59deg.msh")

# Extract coordinates for the nose (Line 1 in gmsh)
nodetag_nose, x_nose, y_nose, z_nose = extractNodes(1, 1)

# Extract coordinates for the cone section (Line 6 in gmsh)
nodetag_cone, x_cone, y_cone, z_cone = extractNodes(1, 6)

# Plot the geometry (optional)
plt.plot(x_nose + x_cone, y_nose + y_cone)
plt.show()

# Enter peak stagnation heat flux
r_n = float(input("Enter nose radius: "))

# Initialize loop
l = 0 # Circumference
noseScaleFac_array = [1]

# A loop to model the heat decline across the nose
for i in range(len(nodetag_nose) - 1):
    # Distance between the two nodes
    dl = math.sqrt((x_nose[i + 1] - x_nose[i])**2 + (y_nose[i + 1] - y_nose[i])**2)

    # Update circumference
    l = l + dl

    # Current angle
    theta = l / r_n

    # Current heat flux
    scaleFac = math.cos(theta)

    # Record q_loc
    noseScaleFac_array.append(scaleFac)

# Linear interpolation for the cone portion
coneScaleFac_array = np.linspace(noseScaleFac_array[-1], noseScaleFac_array[-1] * 0.75, len(nodetag_cone))
coneScaleFac_array = list(coneScaleFac_array)

# Remove duplicate point
nodetag_cone = nodetag_cone[1:]
coneScaleFac_array = coneScaleFac_array[1:]

# Combine a list of node tags and scale factors
sf_list = np.array(list(zip(nodetag_nose + nodetag_cone, noseScaleFac_array + coneScaleFac_array)))

# Write result
with open("sf_list.txt", "w") as f:
    for row in sf_list:
        tag = int(row[0])
        sf = row[1]
        f.write(f"{tag}    {sf}\n")