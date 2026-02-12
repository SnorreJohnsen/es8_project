import numpy as np
import matplotlib.pyplot as plt
import math

def plot_drone_positions(grid_name: str,
                         drone_positions: np.ndarray, 
                         distance: float,
                         range: float):
    
    fig, ax = plt.subplots()
    ax.set_aspect('equal', 'box') 

    ax.set_xlabel("meters", fontsize=16)
    ax.set_ylabel("meters", fontsize=16)

    ax.tick_params(axis='both', labelsize=16)

    # Stating number of drones in mesh
    num_drones = len(drone_positions) 
    ax.set_title(f"{grid_name} Mesh, Drones = {num_drones}, d = {distance} m, d_comm = {range} m", fontsize=16)

    # Plot drone positions as dots
    x_pos = drone_positions[:, 0]
    y_pos = drone_positions[:, 1]
    ax.plot(x_pos, y_pos, 'o', color = 'red')

    for x, y in drone_positions:
        circle = plt.Circle((x, y), range, fill=True, facecolor='blue', edgecolor='black', alpha=0.1)
        ax.add_patch(circle)
  

def make_grid_product(x_range, y_range):
    return np.stack(np.meshgrid(x_range, y_range), axis = -1).reshape(-1,2)

def drone_sq_grid(dim: tuple[float, float],
               dist: float):
    
    x_dim, y_dim = dim
    x_range = np.arange(0,x_dim+1, dist)   
    y_range = np.arange(0,y_dim+1, dist)   

    return make_grid_product(x_range, y_range)
    

def drone_triangle_grid(dim: tuple[float, float],
                   dist: float):
    
    x_dim, y_dim = dim

    # Angle from node in full column to adjacent node in partial column relative to x axis
    alpha = np.radians(30) 
    
    # Calculate y locations for full columns
    full_cols_y_range = np.arange(0, y_dim+1, dist)

    # Calculate number of full comlumns
    full_col_x_dist = 2*dist*np.cos(alpha)
    num_full_cols = math.ceil(x_dim / full_col_x_dist)+1

    full_cols_x_range = np.linspace(0, (num_full_cols-1)*full_col_x_dist, num=num_full_cols)
    full_col_pos = make_grid_product(full_cols_x_range, full_cols_y_range)

    # Calculate number of rows in partal columns
    part_col_num_rows = len(full_cols_y_range)-1

    # linspace(start, start + step*num, num=num, endpoint=False)
    part_cols_y_range = np.linspace(dist*np.sin(alpha), 
                                    dist*np.sin(alpha) + 2*dist*np.sin(alpha)*part_col_num_rows, 
                                    num=part_col_num_rows, 
                                    endpoint=False)
    part_cols_x_range = np.linspace(dist*np.cos(alpha),
                                    dist*np.cos(alpha) + 2*dist*np.cos(alpha)*(num_full_cols-1),
                                    num=num_full_cols-1,
                                    endpoint = False)
    part_col_pos = make_grid_product(part_cols_x_range, part_cols_y_range) 

    full_grid = np.concat([full_col_pos, part_col_pos])
    return full_grid   

def drone_hex_grid_squished(dim: tuple[float, float],
                   dist: float):
    
    x_dim, y_dim = dim

    # Angle next node 
    alpha = np.radians(60)

    # Calculate y locations for full columns
    full_cols_y_range = np.arange(0, y_dim+1, dist)

    # Calculate y locations for part columns
    part_cols_y_range = np.arange(dist/2, y_dim+1, dist)

    # Calculate offsets
    col_x_dist_offset = 2*np.sin(alpha)*dist

    # Generate X positions with alternating step for full columns
    full_x_positions = [0]
    full_stepsize = 0
    full_i = 0
    while full_stepsize < x_dim:
        # Every 2nd step adds the offset
        step = dist if full_i % 2 == 0 else dist + col_x_dist_offset
        full_stepsize = full_x_positions[-1] + step
        if full_stepsize <= x_dim:
            full_x_positions.append(full_stepsize)
        full_i += 1

    full_x_positions = np.array(full_x_positions)

    # Generate grid points for full columns
    full_grid_positions = []
    for col_index, full_cols_x_range in enumerate(full_x_positions):
        # Stagger x by offset if needed for hex pattern (optional)
        full_column_positions = make_grid_product([full_cols_x_range], full_cols_y_range)
        full_grid_positions.append(full_column_positions)

    # Generate X positions with alternating steps for partial columns
    part_x_positions = [dist + col_x_dist_offset/2]  # first point
    part_stepsize = part_x_positions[-1]
    part_i = 0
    while part_stepsize < x_dim:
        # Every 2nd step adds the offset
        step = dist + col_x_dist_offset if part_i % 2 == 1 else dist
        part_stepsize = part_x_positions[-1] + step
        if part_stepsize <= x_dim:
            part_x_positions.append(part_stepsize)
        part_i += 1
    
    part_x_positions = np.array(part_x_positions)

    # Generate grid points for partial columns 
    part_grid_positions = []
    for col_index, part_cols_x_range in enumerate(part_x_positions):
        # Stagger x by offset if needed for hex pattern (optional)
        part_column_positions = make_grid_product([part_cols_x_range], part_cols_y_range)
        part_grid_positions.append(part_column_positions)

    total_grid = np.vstack(full_grid_positions + part_grid_positions)
    return total_grid

def drone_hex_diamond_grid(dim: tuple[float, float],
                   dist: float):
    
    x_dim, y_dim = dim

    # Angle from node in full column to adjacent node in partial column relative to x axis
    alpha = np.radians(30) 
    
    # Calculate y locations for full columns
    full_cols_y_range = np.arange(0, y_dim+1, dist)

    # Calculate number of full comlumns
    full_col_x_dist = 2*dist*np.cos(alpha)
    num_full_cols = math.ceil(x_dim / full_col_x_dist)+1

    full_cols_x_range = np.linspace(0, (num_full_cols-1)*full_col_x_dist, num=num_full_cols)

    # Remove every second instance in arange of full columns
    full_cols_pos_y = full_cols_y_range[::2]

    full_col_pos = make_grid_product(full_cols_x_range, full_cols_pos_y)

    # Calculate number of rows in partal columns
    part_col_num_rows = len(full_cols_y_range)-1

    # linspace(start, start + step*num, num=num, endpoint=False)
    part_cols_y_range = np.linspace(dist*np.sin(alpha), 
                                    dist*np.sin(alpha) + 2*dist*np.sin(alpha)*part_col_num_rows, 
                                    num= math.ceil(part_col_num_rows), 
                                    endpoint=False)
    part_cols_x_range = np.linspace(dist*np.cos(alpha),
                                    dist*np.cos(alpha) + 2*dist*np.cos(alpha)*(num_full_cols-1),
                                    num=num_full_cols-1,
                                    endpoint = False)
    part_col_pos = make_grid_product(part_cols_x_range, part_cols_y_range) 

    full_grid = np.concat([full_col_pos, part_col_pos])
    return full_grid

def drone_hex_grid(dim: tuple[float, float],
                   dist: float):

    x_dim, y_dim = dim
    x_dim = x_dim + dist # added dist for extra column of drones on the right edge

    # Angle next node 
    alpha = np.radians(60)

    # Calculate y locations for full columns
    y_step_size = 2*np.sqrt(dist**2 - (dist/2)**2)
    #full_cols_y_range = np.arange(0, y_dim+1, y_step_size) # original without extra drones on edges
    full_cols_y_range = np.arange(0 - y_step_size/2, y_dim+dist, y_step_size) # added drones on edges

    # Calculate y locations for part columns
    #part_cols_y_range = np.arange(y_step_size/2, y_dim+1, y_step_size) # original without extra drones on edges
    part_cols_y_range = np.arange(0, y_dim+dist, y_step_size) # added drones on edges

    # Calculate offsets
    col_x_dist_offset = 2*np.cos(alpha)*dist

    # Generate X positions with alternating step for full columns
    #full_x_positions = [0] # original without drones on edges
    #full_stepsize = 0 # original stepsize
      
    full_x_positions = [col_x_dist_offset/2] # added drones on the edges
    full_stepsize = full_x_positions[-1] # change stepsize for extra drones on edges
    full_i = 0
    while full_stepsize < x_dim:
        # Every 2nd step adds the offset
        step = dist if full_i % 2 == 0 else dist + col_x_dist_offset
        full_stepsize = full_x_positions[-1] + step
        if full_stepsize <= x_dim:
            full_x_positions.append(full_stepsize)
        full_i += 1

    full_x_positions = np.array(full_x_positions)

    # Generate grid points for full columns
    full_grid_positions = []
    for col_index, full_cols_x_range in enumerate(full_x_positions):
        # Stagger x by offset if needed for hex pattern (optional)
        full_column_positions = make_grid_product([full_cols_x_range], full_cols_y_range)
        full_grid_positions.append(full_column_positions)

    # Generate X positions with alternating steps for partial columns
    #part_x_positions = [dist + col_x_dist_offset/2]  # first point (original without drones on edges)
    #part_stepsize = part_x_positions[-1] # original stepsize
    
    part_x_positions = [0]  # first point (added drones on the edges)
    part_stepsize = 0 # change stepsize for extra drones on edges

    part_i = 0
    while part_stepsize < x_dim:
        # Every 2nd step adds the offset
        #step = dist + col_x_dist_offset if part_i % 2 == 1 else dist  # original - offset on odd 
        step = dist if part_i % 2 == 1 else dist + col_x_dist_offset    # offset on even (starting with partial on left edge)
        part_stepsize = part_x_positions[-1] + step
        if part_stepsize <= x_dim:
            part_x_positions.append(part_stepsize)
        part_i += 1
    
    part_x_positions = np.array(part_x_positions)

    # Generate grid points for partial columns 
    part_grid_positions = []
    for col_index, part_cols_x_range in enumerate(part_x_positions):
        # Stagger x by offset if needed for hex pattern (optional)
        part_column_positions = make_grid_product([part_cols_x_range], part_cols_y_range)
        part_grid_positions.append(part_column_positions)

    total_grid = np.vstack(full_grid_positions + part_grid_positions)
    return total_grid


length = 30000
width = 10000
scale_factor = 1

test_dim = (length*scale_factor, width*scale_factor)
test_distance = 1000
test_range = 1000

drone_pos_hex = drone_hex_grid(test_dim, test_distance)
plot_drone_positions("Hexagonal", drone_pos_hex, distance=test_distance, range=test_range)

drone_pos_hex_diamond = drone_hex_diamond_grid(test_dim, test_distance)
plot_drone_positions("Hexagonal-diamond", drone_pos_hex_diamond, distance=test_distance, range=test_range)

drone_pos_hex_squished = drone_hex_grid_squished(test_dim, test_distance)
plot_drone_positions("Hexagonal-squished", drone_pos_hex_squished, distance=test_distance, range=test_range)

drone_pos_tri = drone_triangle_grid(test_dim, test_distance)
plot_drone_positions("Triangle", drone_pos_tri, distance=test_distance, range=test_range)

drone_pos_sq = drone_sq_grid(test_dim, test_distance)
plot_drone_positions("Square", drone_pos_sq, distance=test_distance, range=test_range)

plt.show()

