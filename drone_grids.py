import numpy as np
import math

def make_grid_product(x_range, y_range):
    return np.stack(np.meshgrid(x_range, y_range), axis = -1).reshape(-1,2)

def drone_sq_grid(dim: tuple[float, float],
                  dist: float):

    x_dim, y_dim = dim
    
    # y positions
    n_drones_column = int(np.floor((y_dim + dist) / dist))      # use np.ceil() for edge_drones
    y_offset = (y_dim - dist*(n_drones_column - 1)) / 2
    y_positions = np.linspace(y_offset,
                              y_offset+dist*(n_drones_column-1),
                              n_drones_column)
    
    # x positions
    n_drones_row = int(np.floor((x_dim + dist) / dist))         # use np.ceil() for edge_drones
    x_offset = (x_dim - dist*(n_drones_row - 1)) / 2
    x_positions = np.linspace(x_offset,
                              x_offset+dist*(n_drones_row-1),
                              n_drones_row)

    full_grid = make_grid_product(x_positions, y_positions)

    return full_grid

def drone_triangle_grid(dim: tuple[float, float],
                        dist: float):
    
    # Parameters
    x_dim, y_dim = dim
    alpha = np.radians(30)
    dist_full_partial = dist * np.cos(alpha)  # distance between full and partial column on x-axis
    step_column = 2*dist_full_partial         # distance between two full columns on x-axis

    # Full columns (y positions)
    n_drones_full_column = int(np.floor((y_dim + dist) / dist))       # number of drones within area on full column
    y_offset_full = (y_dim - dist * (n_drones_full_column - 1)) / 2   # offset from bottom to first drone on y-axis
    y_position_full_column = np.linspace(y_offset_full,
                                         y_offset_full+dist*(n_drones_full_column-1),
                                         n_drones_full_column)        # y locations full column

    # Full columns (x positions)
    n_full_columns = int(np.floor((x_dim + dist) / (step_column)))     # number of full columns (use np.ceil() if you want extra column)
    x_offset_full = (x_dim - step_column * (n_full_columns - 1)) / 2  # offset from left to first drone on x-axis
    x_position_full_column = np.linspace(x_offset_full,
                                         x_offset_full+step_column*(n_full_columns-1),
                                         n_full_columns)              # x locations of full column

    # Partial columns (y positions)
    n_drones_partial_column = n_drones_full_column - 1
    y_offset_partial = (y_dim - dist * (n_drones_partial_column - 1)) / 2
    y_position_partial_column = np.linspace(y_offset_partial,
                                            y_offset_partial+dist*(n_drones_partial_column-1),
                                            n_drones_partial_column)    

    # Partial columns (x positions)
    if x_offset_full + 1e-6 >= dist_full_partial: 
        n_partial_columns = int(np.ceil((x_dim + dist) / step_column))
        x_offset_partial= x_offset_full - dist_full_partial
    else: 
        n_partial_columns = int(np.floor((x_dim + dist) / step_column)) - 1 # number of partial columns (use np.ceil() if you want extra column)
        x_offset_partial = x_offset_full + dist_full_partial
    x_position_partial_column = np.linspace(x_offset_partial,
                                            x_offset_partial+step_column*(n_partial_columns-1),
                                            n_partial_columns)

    # Make Full Grid (combine full and partial for x and y)
    position_full_column = make_grid_product(x_position_full_column, y_position_full_column)
    position_partial_column = make_grid_product(x_position_partial_column, y_position_partial_column)
    full_grid = np.concatenate([position_full_column, position_partial_column])

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
                   dist: float,
                   extra_edge_drones: bool):

    # Angle next node
    alpha = np.radians(60)

    # Calculate offsets
    col_x_dist_offset = 2*np.cos(alpha)*dist

    # Calculate y locations for full columns
    y_step_size = 2*np.sqrt(dist**2 - (dist/2)**2)

    if extra_edge_drones == False:
        x_dim, y_dim = dim
        full_cols_y_range = np.arange(0, y_dim+1, y_step_size) # original without extra drones on edges

        # Calculate y locations for partial columns
        part_cols_y_range = np.arange(y_step_size/2, y_dim+1, y_step_size) # original without extra drones on edges

        # Generate X positions with alternating step for full columns
        full_x_positions = [0] # original without drones on edges
        full_stepsize = 0 # original stepsize

        # Generate X positions with alternating steps for partial columns
        part_x_positions = [dist + col_x_dist_offset/2]  # first point (original without drones on edges)
        part_stepsize = part_x_positions[-1] # original stepsize

    else:
        x_dim, y_dim = dim
        x_dim = x_dim + dist # added dist for extra column of drones on the right edge
        full_cols_y_range = np.arange(0 - y_step_size/2, y_dim+dist, y_step_size) # added drones on edges

        # Calculate y locations for partial columns
        part_cols_y_range = np.arange(0, y_dim+dist, y_step_size) # added drones on edges

        # Generate X positions with alternating step for full columns
        full_x_positions = [col_x_dist_offset/2] # added drones on the edges
        full_stepsize = full_x_positions[-1] # change stepsize for extra drones on edges

        # Generate X positions with alternating steps for partial columns
        part_x_positions = [0]  # first point (added drones on the edges)
        part_stepsize = 0 # change stepsize for extra drones on edges


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


    part_i = 0
    while part_stepsize < x_dim:
        # Every 2nd step adds the offset
        if extra_edge_drones == False:
            step = dist + col_x_dist_offset if part_i % 2 == 1 else dist  # original - offset on odd
        else:
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
