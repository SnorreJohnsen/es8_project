import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.colors as mcolors
import math
import os
import random
import pandas as pd
from tqdm import tqdm
from collections import Counter
from statistics import mean
import argparse
import json
from dataclasses import dataclass, asdict
from scipy.optimize import curve_fit, least_squares
from mesh_design_lib import (
                            distance_calc,
                            shannon,
                            lookup_table_halow_module_MM8108,
                            lookup_table_wifi7_eht_GI0_8_OFDM,
                            lookup_table_wifi7_eht_GI3_2_OFDMA,
                            get_halow_module_MM8108_params,
                            dist_comm_calc,
                            data_rate_given_dist_comm)

metadata = dict()

@dataclass
class Node:
    id: str
    x: int
    y: int
    z: int

@dataclass
class Link:
    source: str
    target: str
    bandwidth_mbit: str
    packet_loss: str

###############################################################################
#__________________________ DRONE MESH GRIDS _________________________________#
###############################################################################
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

###############################################################################
#__________________________ HELPER FUNCTIONS _________________________________#
###############################################################################

def exp_model(x, a, b): # a = scale exponetial function, b = exponetial parameter
    return a * np.exp(-b * x)

def dropout_drones(*,
                   meta_prefix: str = "",
                   drone_positions: np.ndarray,
                   dropout_rate: float) -> np.ndarray:
    """
    Docstring for dropout_drones

    Inputs:
    -------
    meta_prefix: prefix string prepended to metadata keys
    drone_positions: Nx2 numpy array (not mutated)
    dropout_rate: percentage of drones which are removed (0..1)

    Returns:
    -------
    Mx2 numpy array of drones left after dropout.
    Return array originating from copy of drone_positions.
    """

    if dropout_rate > 1 or dropout_rate < 0:
        print(f"dropout_drones: Invalid {dropout_rate=}")
        exit(-1)

    drone_positions_result = drone_positions.copy()

    # Stating number of drones in mesh
    num_drones = len(drone_positions)
    num_drones_dropout = round(num_drones * dropout_rate)
    drone_dropout_perc_real = num_drones_dropout/num_drones # Calculating actual dropout percentage for plot

    # Removing drones from drone positions in relation to dropout
    np.random.shuffle(drone_positions_result)
    if num_drones_dropout == 0:             # Insert to avoid drone_positions_result being [] if num_dropout is 0
        drone_positions_result = drone_positions_result
    else:    
        drone_positions_result = drone_positions_result[:-num_drones_dropout, :]

    # Writing stats to metadata
    metadata[f"{meta_prefix}DROPOUT_REAL_PERCENTAGE"] = drone_dropout_perc_real
    metadata[f"{meta_prefix}DROPOUT_NUM_DRONES"] = num_drones_dropout
    
    return drone_positions_result

def make_device_grid(dim: tuple[float, float],
                     z_height: float,
                     sample_resolution: tuple[float, float]):
    """
    Docstring for make_device_grid
    
    Inputs:
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    z_height: Device height [z]
    sample_resolution: Sample resolution [x, y] i.e. how many sample points inside the dimensions

    Returns: 
    device_positions: NDArray with grid of device positions
    """

    x_dim, y_dim = dim
    x_sample_res, y_sample_res = sample_resolution

    # Device points in drone area
    x_device = np.linspace(0, x_dim, x_sample_res)
    y_device = np.linspace(0, y_dim, y_sample_res)
    X_device, Y_device = np.meshgrid(x_device, y_device)
    Z_device = np.full(X_device.shape, z_height)
    device_positions = np.stack([X_device.ravel(), Y_device.ravel(), Z_device.ravel()], axis=1)

    return device_positions

def calculate_device_links(*,
                           meta_prefix: str = "",
                           nodes: list,
                           dist_comm: float,
                           device_positions: np.ndarray) -> np.ndarray:
    """
    Docstring for calculate_device_links

    Inputs:
    meta_prefix: prefix string prepended to metadata keys
    nodes: List of nodes contataining of drone positions in a given mesh
    dist_comm: Theoretical communication distance of drone in meters
    device_positions: NDArray with grid of device positions

    Returns:
    Saves min and max device links to metadata
    Saves percentage of area covered to metadata
    Saves the minimum squared distance between two nodes
    """

    # Extract drone position from list -> shape (N_points, 2)
    drone_positions = np.asarray([[node.x, node.y, node.z] for node in nodes])

    # Compute squared distances using broadcasting
    # device_points[:, None, :] -> (N_points, 1, 3)
    # drone_positions[None, :, :] -> (1, N_drones, 3)
    # Result -> (N_points, N_drones)
    diff = device_positions[:, None, :] - drone_positions[None, :, :]

    dist_sq = np.sum(diff**2, axis=2)  # shape: (num_devices, num_drones)
    closest_idx = np.argmin(dist_sq, axis=1)
    min_dist_sq = dist_sq[np.arange(dist_sq.shape[0]), closest_idx]

    # Count links per device point
    links_per_device = np.sum(dist_sq <= dist_comm**2, axis=1)

    # Saving min and mean in dict for drone plot
    metadata[f"{meta_prefix}MIN_DEVICE_LINKS"] = float(np.min(links_per_device))
    metadata[f"{meta_prefix}MEAN_DEVICE_LINKS"] = float(np.mean(links_per_device))

    # Area coverage percentage
    covered_points = np.sum(links_per_device > 0)
    total_points = links_per_device.size

    # Save area covered percentage to metadata
    metadata[f"{meta_prefix}AREA_COVERED"] = covered_points / total_points

    return min_dist_sq

def is_network_fully_connected(nodes: list[Node],
                               dist: float) -> bool:
    """
    Docstring for is_network_fully_connected

    Inputs:
    nodes: List of nodes containing drone positions in a given mesh
    dist: Distance between two nodes (square), Distance used to calculate intersection (triangle)

    Returns:
    True if the network is fully connected.
    """

    # checking if all nodes are reachable from each source
    for source in nodes:

        # setup my start reachable source
        cluster = [[source.x, source.y, source.z]]
        visited = {source.id}
        changed = True

        while changed:
            changed = False

            # check which targets i can reach given updated cluster
            for target in nodes:
                if target.id in visited:
                    continue

                for cx, cy, cz in cluster:
                    dx = target.x - cx
                    dy = target.y - cy
                    dz = target.z - cz

                    if dx*dx + dy*dy + dz*dz <= dist**2:
                        cluster.append([target.x, target.y, target.z])
                        visited.add(target.id)
                        changed = True
                        break
        if len(cluster) != len(nodes):
            return False
    return True
                
def checking_max_phyrate_fully_connected(nodes: list[Node],
                                         dist_comm: float,
                                         base_rate: float,
                                         wireless_prefix: str = '',
                                         use_lookup_table: bool = False) -> bool:
    """
    Docstring for checking_max_phyrate_fully_connected
    
    Input:
    nodes: List of nodes contataining of drone positions in a given mesh
    dist_comm: Theoretical communication distance of drone in meters
    base_rate: Base phyrate (the phyrate used for creating mesh)
    wireless_prefix: str, prefix string prepended to metadata keys. Default = ""
    use_lookup_table: bool, for using lookup table (True for datasheet, False for shannon)

    Return:
    The maximum phyrate for a fully connected mesh
    base_rate: If fully connected for dist_comm (base_rate is the maximum phyrate)
    rate: If not fully connected for dist_comm, checks at lower distances (rate is the maximum phyrate)
    If no distance returns fully connected mesh, return 0  
    """
    
    # check for dist_comm
    # if not reachable check less distance
    # continue until found or return fail

    dist = dist_comm

    reached = is_network_fully_connected(nodes=nodes,dist = dist_comm)
    if reached is True:
        return base_rate
    else:
        if use_lookup_table is True:
            rate_ranges = []
            for key, value in metadata.items():
                if key.lower().endswith("_mbps_range"):
                    rate = float(key.split("_")[0])

                    if rate < base_rate:
                        rate_ranges.append((rate, value))
            rate_ranges.sort(key=lambda x: x[0], reverse=True)

            for rate, dist in rate_ranges:
                reached = is_network_fully_connected(nodes=nodes,dist = dist)
                if reached:
                    return rate
            return 0
        
        if use_lookup_table is False:
            rates = np.arange(base_rate, 0, -1)

            for rate in rates:
                shannon_mod_receive_sens_strict = shannon(
                metadata = metadata,
                data_rate_Mbps=rate,
                bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                noise_figure_db=3,
                eta=metadata["ETA_STRICT"],
                snr_eff=metadata["SNR_EFF_STRICT"]
                )
                dist = dist_comm_calc(
                        metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                        shannon_mod_receive_sens_strict,   # use the corresponding receive sens
                        transmit_gain_dbi=0,
                        received_gain_dbi=0,
                        margin_loss_db=3,
                        freq_Mhz=metadata["FREQ_MHZ"]
                    )
            
                reached = is_network_fully_connected(nodes=nodes,dist = dist)

                if reached:
                    return rate
            return 0

def scale_alpha(rate: float,
                min_rate: float,
                max_rate: float):
    
    min_alpha = 0.1
    max_alpha = 0.4
    if max_rate == min_rate:
        return 0.5  # fallback if all rates are equal
    norm = (rate - min_rate) / (max_rate - min_rate)
    return min_alpha + norm * (max_alpha - min_alpha)

def shannon_fit(data_rate, snr_eff, eta,bandwidth):
    # Use the closest_bandwidth (assume constant) and fixed noise figure
    return np.array([
        shannon(
            metadata = metadata,
            data_rate_Mbps=dr,
            bandwidth_Mhz=bandwidth,
            noise_figure_db=3,
            eta=eta,
            snr_eff=snr_eff
        )
        for dr in data_rate
    ])

def residuals(params, data_rate, y, bandwidth):
    snr_eff, eta = params
    pred = shannon_fit(data_rate, snr_eff, eta, bandwidth)

    r = pred - y

    # penalize positive deviations strongly
    r[r < 0] *= 5

    return r

def sort_scheme_for_data_rate(desired_bandwidth_Mhz: float,
                              lookup_table: dict):
    
    """
    Docstring for sort_scheme_for_data_rate:

    Inputs:
    --------
    desired_bandwidth_Mhz : float, Desired bandwidth in MHz used to select the closest available scheme from the lookup table.
    lookup_table : dict, Lookup table containing modulation schemes organized by bandwidth. Each entry includes data rates, transmit power, and receive sensitivities.

    Returns:
    --------
    sorted_schemes : list of dict, List of modulation schemes for the closest available bandwidth, sorted by data rate (ascending).
    closest_bandwidth : int, Closest available bandwidth in MHz from the lookup table to the desired bandwidth.
    """
    
    available_bandwidth = np.array(list(lookup_table.keys()))
    bandwidth_index = np.argmin(np.abs(available_bandwidth - desired_bandwidth_Mhz))
    closest_bandwidth = int(available_bandwidth[bandwidth_index])

    # Get all MCS schemes for that bandwidth
    schemes = lookup_table[closest_bandwidth].values()

    # Find the sorted_scheme with data_rate closest to desired_rate_Mbps
    sorted_schemes = sorted(schemes, key=lambda s: s['data_rate'])

    return sorted_schemes, closest_bandwidth

###############################################################################
#_____________________ NETWORK LISTS (JSON) __________________________________#
###############################################################################

def node_list(drone_positions: np.ndarray) -> list[Node]:
    """
    Docstring for node_list

    Inputs:
    -------
    drone_positions: Nx2 Numpy array of drone positions in a given mesh

    Returns:
    -------
    nodes: list of sorted N Node classes of drone IDs and positions
    """

    # Sort drone positions by x then y
    sorted_pos_indences = np.lexsort((drone_positions[:,1],  # secondary key (y)
                                      drone_positions[:,0])) # primary key (x)

    drone_positions = drone_positions[sorted_pos_indences]

    x_pos = drone_positions[:,0]
    y_pos = drone_positions[:,1]
    z_pos = drone_positions[:,2]

    nodes: list[Node] = []

    for i in range(len(drone_positions)):
        id = f"n{i}"
        node = Node(id=id, x=round(float(x_pos[i]), 2), y=round(float(y_pos[i]), 2), z=round(float(z_pos[i]), 2))
        nodes.append(node)

    return nodes

def link_list(*,
              wireless_prefix: str = "",
              nodes: list,
              dist_comm: float,
              margin_loss_db: float,
              eta: float = 0.79,
              snr_eff: float = 0.14,
              threshold_link: float = 0,
              use_lookup_table: bool = False) -> list[Link]:

    """
    Docstring for link_list

    Inputs:
    -------
    nodes: list of sorted N Node classes of drone IDs and positions
    dist_comm: Theoretical communication distance of drone in meters
    threshold_link: float,
    use_lookup_table: bool for using lookup table (True for datasheet, False for shannon)

    Returns:
    -------
    links: list of N Link classes with sources and respective targets
    num_links_video: Nx1 numpy array of links for each drone
    num_links_cmd: 
    """

    links: list[Link] = []
    num_links_video = []
    num_links_cmd = []
    for source in nodes:
        count = 0
        count_cmd = 0
        for target in nodes:

            if target.id == source.id:
               continue
            
            # Compute distances from drone i to all drones
            distances = (target.x - source.x)**2 + (target.y - source.y)**2 + (target.z - source.z)**2
               
            if use_lookup_table == False:

                # if distances <= (dist_comm + 1)**2:
                #predicted_rate= exp_model(np.sqrt(distances), scale_exp, exp_param)
                links, count, count_cmd = link_shannon(
                             distance_sq = distances,
                             eta = eta,
                             snr_eff = snr_eff,
                             margin_loss_db = margin_loss_db,
                             links = links,
                             target=target,
                             source = source,
                             threshold_link=threshold_link,
                             count = count,
                             count_cmd=count_cmd
                             )
            else:
                links, count, count_cmd = link_datasheet(distance_sq =distances,
                                                                          links = links,
                                                                          target = target,
                                                                          source = source,
                                                                          threshold_link=threshold_link,
                                                                          count = count,
                                                                          count_cmd=count_cmd
                                                                           )   
    
        num_links_video.append(count)
        num_links_cmd.append(count_cmd)
        
    return links, num_links_video, num_links_cmd

def link_shannon(
                 distance_sq: float,
                 eta: float,
                 snr_eff: float,
                 margin_loss_db: float,
                 links: list,
                 target,
                 source,
                 threshold_link: float,
                 count: int,
                 count_cmd: int,
                 wireless_prefix: str = ""):
    """
    Docstring for link_shannon:

    Inputs:
    -------
    distance_sq: float, Squared distance between the source and target nodes (m^2).
    eta: float, Spectral efficiency factor used in the Shannon calculation.
    snr_eff: float, Effective signal-to-noise ratio used in the Shannon calculation.
    margin_loss_db: float, Additional loss margin in dB applied to the link budget.
    links: list, valid Link objects will be appended to this list.
    target: object, Target node object. Must have an `id` attribute.
    source: object, Source node object. Must have an `id` attribute.
    threshold_link: float, Minimum required data rate (Mbps) for a link to be considered valid.
    count: int, Counter for links with phyrate above the "video" communication range.
    count_cmd: int, Counter for links with phyrate above the "command" communication range.
    wireless_prefix: str, optional. Default is "".

    Returns:
    -------
    links: list, Updated list of Link objects that satisfy the threshold condition.
    count: int, Updated count of links above the high data rate (video).
    count_cmd: int, Updated count of links above the low data rate (command).
    """

    data_rate_mbps = data_rate_given_dist_comm(distance_m=distance_sq,
                                                bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                                                transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                                                margin_loss_db=margin_loss_db,
                                                eta=eta,
                                                snr_eff=snr_eff,
                                                freq_Mhz=metadata["FREQ_MHZ"])
    
    rngs = []
    for s in [20,0.1]:
        shannon_mod_receive_sens_strict = shannon(
                metadata = metadata,
                data_rate_Mbps=s,
                bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                noise_figure_db=3,
                eta=metadata["ETA_STRICT"],
                snr_eff=metadata["SNR_EFF_STRICT"]
            )
        rng = dist_comm_calc(
                metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                shannon_mod_receive_sens_strict,   # use the corresponding receive sens
                transmit_gain_dbi=0,
                received_gain_dbi=0,
                margin_loss_db=3,
                freq_Mhz=metadata["FREQ_MHZ"]
            )
        rngs.append(rng)
    rng_video, rng_100_kbps= rngs

    metadata["histogram_low_rate"] = 0.1
    metadata["histogram_high_rate"] = 20

    if data_rate_mbps > threshold_link:
                link = Link(source=source.id,
                                target=target.id,
                                bandwidth_mbit=f"{data_rate_mbps:.2f}",
                                packet_loss = "10") # 10%
                links.append(link)

                if distance_sq <= (rng_video + 1)**2:
                    # Count how many are within dist_comm (exclude itself)
                    count = count + 1
                
                if distance_sq <= (rng_100_kbps + 1)**2:
                    count_cmd = count_cmd + 1

    return links, count, count_cmd

def link_datasheet(distance_sq: float,
                   links: list,
                   target,
                   source,
                   threshold_link: float,
                   count: int,
                   count_cmd: int,
                   wireless_prefix: str = ""
                   ):
    
    """
    Docstring for link_datasheet:

    Inputs:
    -------
    distance_sq: float, Squared distance between the source and target nodes (m^2).
    links: list, valid Link objects will be appended to this list.
    target: object, Target node object. Must have an `id` attribute.
    source: object, Source node object. Must have an `id` attribute.
    threshold_link: float, Minimum required data rate (Mbps) for a link to be included in JSON.
    count: int, Counter for links with phyrate above the "video" communication range.
    count_cmd: int, Counter for links with phyrate above the "command" communication range.
    wireless_prefix: str, optional. Default is "".

    Returns:
    -------
    links: list, Updated list of Link objects that satisfy the threshold condition.
    count: int, Updated count of links above the high data rate (video).
    count_cmd: int, Updated count of links above the low data rate (command).
    """

    rate_ranges = []
    for key, value in metadata.items():
        if key.lower().endswith("_mbps_range"):
            rate = float(key.split("_")[0])
            rate_ranges.append((rate, value))

    rate_ranges.sort(key=lambda x: x[0], reverse=True)
    data_rate_mbps = 0
    # find correct rate

    for rate, rng in rate_ranges:
        if distance_sq <= rng**2:
            data_rate_mbps = rate
            break

    results = []
    for r in [20, 0.1]:
        for rate, rng in reversed(rate_ranges):
            if rate >= r:
                results.append((rate, rng))
                break
        else:
            # fallback if nothing >= r
            results.append(rate_ranges[-1])

    (rng_video_rate, rng_video), (rng_100_rate, rng_100_kbps) = results
    metadata["histogram_low_rate"] = rng_100_rate
    metadata["histogram_high_rate"] = rng_video_rate

    if data_rate_mbps > threshold_link:
        link = Link(source=source.id,
                    target=target.id,
                    bandwidth_mbit=f"{data_rate_mbps:.2f}",
                    packet_loss="10") # 10%
                    # data_rate=str(metadata[f"{wireless_prefix}DATA_RATE"]))
        links.append(link)

        if distance_sq <= (rng_video + 1)**2:
        # Count how many are within dist_comm (exclude itself)
            count = count + 1
        
        if distance_sq <= (rng_100_kbps + 1)**2:
            count_cmd = count_cmd + 1


    return links, count, count_cmd

def make_json_network(*,
                      file_name: str,
                      file_folder_path: str,
                      nodes: list,
                      links: list):
    """
    Docstring for make_json_network:

    Inputs:
    -------
    file_name: str, Name of the JSON file to be created.
    file_folder_path: str, Path to the folder where the JSON file will be saved.
    nodes: list, List of node objects (dataclasses) to be included in the network.
    links: list, List of link objects (dataclasses) to be included in the network.

    Returns:
    -------
    Writes the network structure (nodes and links) to a JSON file.
    """

    network = dict()

    network["nodes"] = [asdict(i) for i in nodes]
    network["links"] = [asdict(j) for j in links]

    with open(os.path.join(file_folder_path, file_name), "w") as f:
        json.dump(network, f)

###############################################################################
#___________________________ PLOT FUNCTIONS __________________________________#
###############################################################################

def plot_drone_positions(*,
                         meta_prefix: str = "",
                         wireless_prefix: str = "",
                         title_name: str,
                         file_name: str,
                         nodes: list,
                         device_positions: np.ndarray,
                         distance: float,
                         dist_comm: float,
                         thresholds_phyrate: list[float],
                         dist_device_to_drone: np.ndarray,
                         links: list,
                         eta: float,
                         snr_eff: float,
                         dim: tuple [float,float],
                         file_folder_path: str,
                         use_lookup_table: bool,
                         font_size: float = 8.0):

    """
    Docstring for plot_drone_positions:

    Inputs:
    --------
    meta_prefix: str, optional. Default is "".
    wireless_prefix: str, optional. Default is "".
    title_name: str, Title of the plot.
    file_name: str, Name of the file where the plot will be saved.
    nodes: list, List of node objects. Each node must have [x,y] attributes.
    device_positions: np.ndarray, Array of device positions with shape (N, 2).
    distance: float, Distance between drones (used for display in title).
    dist_comm: float, Communication distance threshold (used for display in title).
    thresholds_phyrate: list[float], List of PHY rate thresholds (Mbps) used to draw coverage regions.
    dist_device_to_drone: np.ndarray, Array of squared distances between devices and drones (m^2).
    links: list, List of Link objects containing bandwidth information.
    eta: float, Spectral efficiency factor used in the Shannon calculation.
    snr_eff: float, Effective signal-to-noise ratio used in the Shannon calculation.
    dim: tuple[float, float], Dimensions (length, width) of the plotted area.
    file_folder_path: str, Path to the folder where the plot will be saved.
    use_lookup_table: bool, If True, uses predefined rate-distance lookup table; otherwise uses Shannon model.
    font_size: float, optional

    Returns:
    -------
    Generates and saves a plot visualizing drone positions, device positions, communication ranges, and PHY rate thresholds.
    """

    fig, ax_drone_pos = plt.subplots()

    # Plot drone positions as dots form node list
    x_pos = [node.x for node in nodes]
    y_pos = [node.y for node in nodes]
    x_device_pos = device_positions[:,0]
    y_device_pos = device_positions[:,1]
    # only plot device if there is less than or equal to 300 devices
    if len(x_device_pos) <= 300:
        ax_drone_pos.plot(x_device_pos, y_device_pos, 'o', color = 'green', markersize=1)
    ax_drone_pos.plot(x_pos, y_pos, 'o', color = 'red', markersize=2)
    
    device_links_rate = []
    if not use_lookup_table:
        # dist_device_to_drone should already be squared distances
        for dist_sq in dist_device_to_drone:
            dist = np.sqrt(dist_sq)  # only here

            data_rate_mbps = data_rate_given_dist_comm(
                distance_m=dist,
                bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                margin_loss_db=metadata["MARGIN_LOSS"],
                eta=eta,
                snr_eff=snr_eff,
                freq_Mhz=metadata["FREQ_MHZ"]
            )

            device_links_rate.append(round(float(data_rate_mbps), 2))
    else:
        rate_ranges = []
        for key, value in metadata.items():
            if key.lower().endswith("_mbps_range"):
                rate = float(key.split("_")[0])
                rate_ranges.append((rate, value))

        rate_ranges.sort(key=lambda x: x[0], reverse=True)

        for dist_sq in dist_device_to_drone:
            data_rate_mbps = 0

            for rate, rng in rate_ranges:
                if dist_sq <= rng**2:
                    data_rate_mbps = rate
                    break
            device_links_rate.append(data_rate_mbps)

    phyrates = [float(link.bandwidth_mbit) for link in links]
    if not phyrates:
        phyrates = [0]

    rate_ranges = []

    for key, value in metadata.items():
        if key.lower().endswith("_mbps_range"):
            rate = float(key.split("_")[0])
            rate_ranges.append((rate, value))

    rate_ranges.sort(key=lambda x: x[0])

    threshold_distances = []
    matched_rates = []
    if use_lookup_table == True:
        for threshold in thresholds_phyrate:
            chosen_range = None
            for rate, rng in rate_ranges:
                if threshold <= rate:   # round up to next supported rate
                    chosen_range = rng
                    chosen_rate = rate
                    break

            # if threshold larger than all available rates
            if chosen_range is None:
                chosen_rate, chosen_range = rate_ranges[-1]

            threshold_distances.append(chosen_range)
            matched_rates.append(chosen_rate)
        thresholds_phyrate = matched_rates
    else:
        threshold_sensivities = [ shannon(
                metadata=metadata,
                data_rate_Mbps=threshold,
                bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                noise_figure_db=3,
                eta=metadata["ETA_STRICT"],
                snr_eff=metadata["SNR_EFF_STRICT"],
                wireless_prefix=wireless_prefix
            )
            for threshold in thresholds_phyrate 
            ]
        
        threshold_distances= [ dist_comm_calc(
            transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
            received_power_dbm=threshold_sensivity,
            freq_Mhz=metadata["FREQ_MHZ"],
            margin_loss_db=metadata["MARGIN_LOSS"]
        ) 
        for threshold_sensivity in threshold_sensivities
        ]

    # assign colors (can be longer than three thresholds)
    cmap = plt.get_cmap('viridis')
    n_thresh = len(threshold_distances)
    if n_thresh == 1:
        threshold_colors = [cmap(0.5)]
    else:
        threshold_colors = [cmap(1 - i/(n_thresh-1)) for i in range(n_thresh)]


    # Deduplicate the rates
    seen = set()

    filtered = [
        (dist, rate, color)
        for dist, rate, color in zip(threshold_distances, thresholds_phyrate, threshold_colors)
        if not (rate in seen or seen.add(rate))
    ]

    threshold_distances, thresholds_phyrate, threshold_colors = map(list, zip(*filtered))

    sorted_thresh = sorted(zip(threshold_distances, thresholds_phyrate, threshold_colors),
                           key=lambda x: x[0], reverse=True)
    legend_handles = []

    min_rate = min(thresholds_phyrate)
    max_rate = max(thresholds_phyrate)

    # draw smallest circles first (so bigger circles are underneath)
    for dist, rate, color in sorted_thresh:
        # to be able to see overlap, remove and set alpha = 1 and remove linewidth to get pure heatmap
        alpha = scale_alpha(rate,min_rate,max_rate)
        for node in nodes:
            x, y = node.x, node.y
            label = f"{rate:.2f} Mbps ({dist:.1f} m)"
            circle = plt.Circle(
                (x, y),
                dist,
                fill=True,
                facecolor=color,
                edgecolor='black',   # edge color
                linewidth=alpha*2,   # edge thickness
                alpha=alpha 
                # for getting pure heatmap change to and remove edgedcolor and linewidth
                # alpha = 1,

            )
            ax_drone_pos.add_patch(circle)
            legend_handles.append(circle)
    length, width = dim
    square = Rectangle((0, 0),length, width, edgecolor='white', fill=False)
    ax_drone_pos.add_patch(square)

    drone_height = metadata["DRONE_HEIGHT"]
    device_height = metadata["DEVICE_HEIGHT"]

    height_diff = abs(drone_height - device_height)

    title_text = (
    f"{title_name}\n"
    f"Drones = {len(nodes)}, d = {distance:.2f} [m], dist_comm = {dist_comm:.2f} [m] \n"
    f"Drone PHYrate [Mbps]: Min = {min(phyrates):.2f}, Avg = {mean(phyrates):.2f}, Max = {max(phyrates):.2f} \n"
    f"Device PHYrate [Mbps]: Min = {np.min(device_links_rate):.2f}, Avg = {np.mean(device_links_rate):.2f} | Height = {height_diff:.0f} [m]"
    )

    ax_drone_pos.set_title(title_text, fontsize=font_size, fontweight='bold', x=0.3,pad=15)  # set a bit to the left and further up
    ax_drone_pos.set_xlabel("[m]", fontsize=font_size)
    ax_drone_pos.set_ylabel("[m]", fontsize=font_size)
    ax_drone_pos.set_aspect('equal', 'box')
    ax_drone_pos.set_xlim(-10000, 40000)
    ax_drone_pos.set_ylim(-5000, 15000)
    ax_drone_pos.tick_params(axis='both', labelsize=font_size)
    # Create legend handles for the legend only
    for dist, rate, color in sorted_thresh:
        ax_drone_pos.scatter([], [], color=color, alpha=0.3,
                            label=f"{rate:.2f} Mbps ({dist:.1f} m)")
    ax_drone_pos.legend(
            title="Thresholds",
            loc='lower right',
            bbox_to_anchor=(1.1, 1.05),
            fontsize=8,
            frameon=False               # optional: no box
    )

    file_path = os.path.join(file_folder_path, file_name)
    fig.savefig(file_path, dpi=300, bbox_inches='tight')

    plt.close(fig)

def plot_drone_links(*,
                         title_name: str,
                         file_name: str,
                         nodes: list,
                         links: list,
                         file_folder_path: str,
                         source_node: str = "",
                         threshold_phyrate_links: float = 0.0,
                         font_size: float = 8.0):
    
    """
    Docstring for plot_drone_links:

    Inputs:
    --------
    title_name: str, Title of the plot.
    file_name: str, Name of the file where the plot will be saved.
    nodes: list, List of node objects. Each node must have [id, x, y] attributes.
    links: list, List of Link objects containing source, target, and bandwidth information.
    file_folder_path: str, Path to the folder where the plot will be saved.
    source_node: str, optional. Default is "".
    threshold_phyrate_links: float, Minimum PHY rate (Mbps) required for links to be displayed.
    font_size: float, optional

    Returns:
    -------
    Generates and saves a plot visualizing links from a selected source node, where link color represents bandwidth.
    """

    id_pos = [node.id for node in nodes]

    # Case 1: No input, pick randomly
    if source_node == "":
        source_node = random.choice(id_pos)
    else:
        if source_node in id_pos:
            pass  # good, source_node is valid
        else:
            # Count down until you find an existing ID
            found = False
            # Work when ids are set as "n21,22,..."
            num = int(''.join(filter(str.isdigit, source_node)))
            prefix = ''.join(filter(str.isalpha, source_node))
            while num > 0:
                candidate = f"{prefix}{num}"
                if candidate in id_pos:
                    source_node = candidate
                    found = True
                    break
                num -= 1
            if not found:
                # Fallback: pick random
                source_node = random.choice(id_pos)

    source_links = [link for link in links if link.source == source_node]

    # Extract positions
    x_pos = [node.x for node in nodes]
    y_pos = [node.y for node in nodes]
    node_dict = {node.id: (node.x, node.y) for node in nodes}

    # Prepare bandwidth for coloring
    all_bw = [float(link.bandwidth_mbit) for link in source_links]
    if not all_bw:
        all_bw = [0]
    norm = mcolors.Normalize(vmin=min(all_bw), vmax=max(all_bw))
    cmap = plt.cm.viridis

    fig, ax = plt.subplots(figsize=(16,9))
    for link in sorted(source_links, key=lambda l: float(l.bandwidth_mbit)):
        src = link.source
        tgt = link.target
        bw = float(link.bandwidth_mbit)
        if bw > threshold_phyrate_links:
            x1, y1 = node_dict[src]
            x2, y2 = node_dict[tgt]
            color = cmap(norm(bw))
            ax.annotate(
                '',
                xy=(x2, y2),
                xytext=(x1, y1),
                arrowprops=dict(
                    arrowstyle='->',
                    color=color,
                    lw=2
                )
            )

    # Draw nodes
    ax.scatter(x_pos, y_pos, color='red', s=20)

    # Optional colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.5)
    cbar.set_label("Bandwidth (Mbit)")

    title_text = (
    f"{title_name}\n"
    f"Drones = {len(nodes)}, Selected source node: {source_node} \n"
    f"Showing links with Phyrates above {threshold_phyrate_links} [Mbps]"
    )
    ax.set_title(title_text, fontsize=font_size*2, fontweight='bold')
    ax.set_xlabel("[m]", fontsize=font_size)
    ax.set_ylabel("[m]", fontsize=font_size)
    ax.set_aspect('equal', 'box')

    file_path = os.path.join(file_folder_path, file_name)
    fig.savefig(file_path, dpi=300, bbox_inches='tight')

    plt.close(fig)

def link_matrix(links: list,
                nodes:list,
                file_folder_path: str,
                file_name: str):
    """
    Docstring for link_matrix:

    Inputs:
    --------
    links: list, List of Link objects containing source, target, and bandwidth information.
    nodes: list, List of node objects. Each node must have [id, x, y] attributes.
    file_folder_path: str, Path to the folder where the LaTeX file will be saved.
    file_name: str, Name of the LaTeX file (without extension).

    Returns:
    -------
    Generates and saves a LaTeX table representing the link bandwidth matrix,
    where each cell is color-coded based on the PHY rate between nodes.
    """

    node_dict = {node.id: (node.x, node.y) for node in nodes}
    node_ids = sorted(node_dict, key=lambda x: int(x[1:]))

    link_lookup = {(link.source, link.target): float(link.bandwidth_mbit) for link in links}

    # colormap
    all_bw = [float(link.bandwidth_mbit) for link in links]
    if not all_bw:
        all_bw = [0]
    norm = mcolors.Normalize(vmin=min(all_bw), vmax=max(all_bw))
    cmap = plt.cm.viridis

    # Build data
    data = []
    row_labels = []
    col_labels = []

    for nid in node_ids:
        x, y = node_dict[nid]
        col_labels.append(f"{nid}")

    for src_id in node_ids:
        x, y = node_dict[src_id]
        row_labels.append(f"{src_id}")
        row = []
        for tgt_id in node_ids:
            if src_id == tgt_id:
                row.append(np.nan)  # diagonal
            else:
                bw = link_lookup.get((src_id, tgt_id), np.nan)
                if bw == 0.0:
                    bw = np.nan
                row.append(bw)
        data.append(row)

    df = pd.DataFrame(data, index=row_labels, columns=col_labels)

    # Create LaTeX strings 
    def latex_cell(val):
        if pd.isna(val):
            return r"\cellcolor[RGB]{200,200,200}"  # diagonal or missing
        color = cmap(norm(val))
        r, g, b = int(color[0]*255), int(color[1]*255), int(color[2]*255)
        return rf"\cellcolor[RGB]{{{r},{g},{b}}} {val:.1f}"

    df_latex = df.map(latex_cell)

    df_latex.to_latex(
        f"{file_folder_path}{file_name}.tex",
        escape=False,   # keep \cellcolor commands
        index=True
    )

def plot_histogram_drone_links(*,
                               file_name: str,
                               title_name: str,
                               drone_link_count: list,
                               iterations: int = 1,
                               file_folder_path: str,
                               font_size: float = 16.0):
    
    """
    Docstring for plot_histogram_drone_links:

    Inputs:
    --------
    file_name: str, Name of the file where the histogram will be saved.
    title_name: str, Title of the histogram plot.
    drone_link_count: list, List containing the number of links per drone.
        Can be a flat list or a list of lists (e.g., from multiple iterations).
    iterations: int, Number of iterations used to average the histogram values. Default is 1.
    file_folder_path: str, Path to the folder where the plot will be saved.
    font_size: float, optional

    Returns:
    -------
    Generates and saves a histogram showing the distribution of the number of links per drone.
    """

    # Build histogram of # drones and # links
    fig_hist, ax_hist = plt.subplots(figsize=(8,5))

    # Flatten if input is list of lists
    if any(isinstance(i, list) for i in drone_link_count):
        drone_link_count = [count for sublist in drone_link_count for count in sublist]

    connections_hist = Counter(drone_link_count)

    # Compute average for each bin in histogram
    connections_hist_avg = {key: value / iterations for key, value in connections_hist.items()}

    # Sort keys to ensure ordered x-axis
    x_values = sorted(connections_hist_avg.keys())
    y_values = [connections_hist_avg[x] for x in x_values]

    title_text = (
        f"{title_name}"
    )

    ax_hist.set_title(title_text, fontsize=font_size, fontweight='bold')
    ax_hist.set_xlabel("Connections", fontsize=font_size)
    ax_hist.set_ylabel("Drones", fontsize=font_size)

    # Center bars on integers
    bars = ax_hist.bar(x_values, y_values, width=0.2)

    # Places value of bin over bin
    for bar in bars:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            f'{float(height)}',
            ha='center',
            va='bottom',
            fontsize = font_size
            )

    # Show only integer ticks (only existing values)
    ax_hist.set_xticks(range(np.max(x_values)+1))
    ax_hist.set_xlim(-0.5, np.max(x_values)+0.5)
    ax_hist.set_ylim(0, np.max(y_values)+0.15*np.max(y_values))
    ax_hist.tick_params(axis='both', labelsize=font_size*0.9)
    file_path_hist = os.path.join(file_folder_path, file_name)
    fig_hist.savefig(file_path_hist, dpi=300, bbox_inches='tight')
    plt.close(fig_hist)

def graph_sensitivity_phyrate(metadata: dict,
                              file_folder_path: str,
                              filename: str,
                              desired_bandwidth_Mhz: float,
                              lookup_table:dict,
                              lookup_table_name: str,
                              enable_plot: bool
                              ):
    """
    Docstring for graph_sensitivity_phyrate:

    Inputs:
    --------
    metadata: dict, Dictionary containing system parameters.
    file_folder_path: str, Path to the folder where the plot will be saved.
    filename: str, Name of the output file (without extension).
    desired_bandwidth_Mhz: float, Desired bandwidth used to select the closest scheme from the lookup table.
    lookup_table: dict, Lookup table containing modulation schemes with data rates and sensitivities.
    lookup_table_name: str, Name of the lookup table (used for labeling in the plot).
    enable_plot: bool, If True, generates and saves the sensitivity vs PHY rate plot.

    Returns:
    -------
    Updates metadata with fitted Shannon parameters (optimal and strict) and optionally generates and saves a plot comparing datasheet values with Shannon-based models.
    """

    # For desired bandwidth
    sorted_schemes, closest_bandwidth = sort_scheme_for_data_rate(desired_bandwidth_Mhz,lookup_table)

    # Take the values out from the lookup table
    data_rates = [s['data_rate'] for s in sorted_schemes]
    sensitivities = [s['receive_sensitivity'] for s in sorted_schemes]

    # Standard shannon
    shannon_receive_sens = [
        shannon(
            metadata = metadata,
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            eta=1,
            snr_eff=1,
            noise_figure_db=3
        )
        for data_rate in data_rates
    ]

    # fit the best parameters for snr_eff and eta to fit the datasheet
    # For desired MHz bandwidth
    popt, pcov = curve_fit(
        lambda dr, snr_eff, eta:
            shannon_fit(dr, snr_eff, eta, closest_bandwidth),
        data_rates,
        sensitivities,
        p0=[0.1, 0.8]
    )
    snr_eff_opt, eta_opt = popt

    fitted_sens = shannon_fit(
        data_rates,
        snr_eff_opt,
        eta_opt,
        closest_bandwidth
    )

    # trying to fit curve strictly speaking, penatilties over estimating range
    res = least_squares(
    residuals,
    x0=[0.1, 0.8],
    args=(data_rates, sensitivities,closest_bandwidth)
    )

    snr_eff_strict, eta_strict = res.x

    strict_fitted_sens = shannon_fit(
        data_rates,
        snr_eff_strict,
        eta_strict,
        closest_bandwidth
    )

    metadata[f"SNR_EFF_OPTIMAL"] = snr_eff_opt
    metadata[f"SNR_EFF_STRICT"] = snr_eff_strict
    metadata[f"ETA_OPTIMAL"] = eta_opt
    metadata[f"ETA_STRICT"] = eta_strict

    if enable_plot == True:
        os.makedirs(file_folder_path,exist_ok=True)
        # create plot
        fig, ax1 = plt.subplots(figsize=(16, 9))

        ax1.set_xlabel("Receive Sensitivity (dBm)", fontsize=16)
        ax1.set_ylabel("PHY Rate (Mbps)", fontsize=16)
        ax1.tick_params(axis='both', which='major', labelsize=16)
        ax1.plot(shannon_receive_sens, data_rates, label="Shannon",color = "lightblue")
        ax1.plot(sensitivities, data_rates,'x',color = "orange")
        ax1.step(sensitivities, data_rates, where='post',color="orange", label=f"Datasheet {lookup_table_name}")
        ax1.plot(fitted_sens, data_rates, color="green", label=f"Modified Shannon {lookup_table_name} Optimal snr_eff: {snr_eff_opt:.2f}, eta: {eta_opt:.2f}, {desired_bandwidth_Mhz} Mhz BW")
        ax1.plot(strict_fitted_sens, data_rates,color="red", label=f"Modified Shannon {lookup_table_name} Strict snr_eff: {snr_eff_strict:.2f}, eta: {eta_strict:.2f}, {desired_bandwidth_Mhz} Mhz BW")
        
        ax1.legend(fontsize=18, loc='upper left')
        file_path_graph = os.path.join(file_folder_path, filename + ".png")
        fig.savefig(file_path_graph,dpi=300,bbox_inches='tight')
        plt.close(fig)

def graph_range_phyrate(metadata: dict,
                        file_folder_path: str,
                        filename: str,
                        desired_bandwidth_Mhz: float,
                        lookup_table: dict,
                        lookup_table_name: str,
                        enable_plot: bool
                        ):
    """
    Docstring for graph_range_phyrate:

    Inputs:
    --------
    metadata: dict, Dictionary containing system parameters (e.g., frequency, fitted Shannon parameters).
    file_folder_path: str, Path to the folder where output files (plot and table) will be saved.
    filename: str, Name of the output plot file (without extension).
    desired_bandwidth_Mhz: float, Desired bandwidth used to select the closest scheme from the lookup table.
    lookup_table: dict, Lookup table containing modulation schemes with data rates, transmit power, and sensitivities.
    lookup_table_name: str, Name of the lookup table (used for labeling in the plot).
    enable_plot: bool, If True, generates and saves the range vs PHY rate plot and LaTeX table.

    Returns:
    -------
    Updates metadata with communication ranges per PHY rate and optionally
    generates and saves a plot and LaTeX table comparing datasheet values with
    modified Shannon-based models.
    """

    data_rates = []
    dist_comms = []

    sorted_schemes, closest_bandwidth = sort_scheme_for_data_rate(desired_bandwidth_Mhz,lookup_table)

    # Take the values out from the lookup table
    data_rates = [ s['data_rate'] for s in sorted_schemes]
    dist_comms= [ dist_comm_calc(s['transmit_power'],s['receive_sensitivity'],transmit_gain_dbi=0,received_gain_dbi=0,margin_loss_db=3,freq_Mhz=metadata["FREQ_MHZ"]) for s in sorted_schemes]

    shannon_mod_receive_sens_strict = [
        shannon(
            metadata = metadata,
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3,
            eta=metadata["ETA_STRICT"],
            snr_eff=metadata["SNR_EFF_STRICT"]
        )
        for data_rate in data_rates
    ]
    
    dist_comms_mod_shannon_strict = [
        dist_comm_calc(
            s['transmit_power'],
            shannon_mod_receive_sens_strict[i],   # use the corresponding receive sens
            transmit_gain_dbi=0,
            received_gain_dbi=0,
            margin_loss_db=3,
            freq_Mhz=metadata["FREQ_MHZ"]
        )
        for i, s in enumerate(sorted_schemes)
    ]

    # Created the curve based of the fitted modified shannon
    shannon_mod_receive_sens_optimal = [
        shannon(
            metadata = metadata,
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3,
            eta=metadata["ETA_OPTIMAL"],
            snr_eff=metadata["SNR_EFF_OPTIMAL"]
        )
        for data_rate in data_rates
    ]
    dist_comms_mod_shannon_optimal= [
        dist_comm_calc(
            s['transmit_power'],
            shannon_mod_receive_sens_optimal[i],   # use the corresponding receive sens
            transmit_gain_dbi=0,
            received_gain_dbi=0,
            margin_loss_db=3,
            freq_Mhz=metadata["FREQ_MHZ"]
        )
        for i, s in enumerate(sorted_schemes)
    ]

    os.makedirs(file_folder_path,exist_ok=True)

    # Create table with deviation values
    total_deviation_opt = 0
    total_deviation_strict = 0
    rows = []   # table storage
    for x, y, z_opt, z_strict in zip(dist_comms,
                                data_rates,
                                dist_comms_mod_shannon_optimal,
                                dist_comms_mod_shannon_strict):
        deviation_opt = x - z_opt
        deviation_strict = x - z_strict
        total_deviation_opt += abs(deviation_opt)
        total_deviation_strict += abs(deviation_strict)
        # store row for table
        rows.append({
            "PHY Rate (Mbps)": f"{y:.2f}",
            "Datasheet (m)": f"{x:.2f}",
            "Optimal (m)": f"{z_opt:.2f}",
            "Strict (m)": f"{z_strict:.2f}",
            "Deviation Optimal (m)": f"{deviation_opt:.2f}",
            "Deviation Strict (m)": f"{deviation_strict:.2f}",
        })
        metadata[f"{y:.2f}_Mbps_range"] = x
    
    # averages
    avg_deviation_opt = total_deviation_opt / len(dist_comms)
    avg_deviation_strict = total_deviation_strict / len(dist_comms)

    # FIGURE
    if enable_plot == True:

        # create table
        df = pd.DataFrame(rows)
        df.to_latex(f"{file_folder_path}_table_bandwidth_{desired_bandwidth_Mhz}_MHz.tex", index=False)

        fig, ax1 = plt.subplots(figsize=(16, 9))
        plt.xscale('log')  # set x-axis to logarithmic
        ax1.set_xlabel("Range (m)", fontsize=18)
        ax1.set_ylabel("PHY Rate (Mbps)", fontsize=18)
        ax1.tick_params(axis='both', which='major', labelsize=16)
        ax1.plot(dist_comms, data_rates,'x',color = "orange")
        ax1.step(dist_comms, data_rates, where='post', label=f"Datasheet {lookup_table_name}", color = "orange")
        ax1.plot(dist_comms_mod_shannon_optimal, data_rates, color="green", label=f"Modified shannon {lookup_table_name} with avg deviation of {avg_deviation_opt:.2f} (m) optimal")
        ax1.plot(dist_comms_mod_shannon_strict, data_rates, color="red", label=f"Modified shannon {lookup_table_name} with avg deviation of {avg_deviation_strict:.2f} (m) strict")

        ax1.legend(fontsize=18, loc='upper right')
        file_path_graph = os.path.join(file_folder_path, filename + ".png")
        fig.savefig(file_path_graph,dpi=300, bbox_inches = 'tight')
        plt.close(fig)

###############################################################################
#___________________________ EXECUTIVE FUNCTIONS _____________________________#
###############################################################################

def process_drone_mesh(*,
                       grid_prefix: str,
                       wireless_prefix: str = "",
                       dist_comm: float,
                       dim: tuple[float, float],
                       drone_height: float,
                       tolerances: np.ndarray,
                       drone_distance_redundancy: float,
                       dropout_rates: np.ndarray,
                       dropout_iters: int,
                       margin_loss_db: float,
                       device_grid: np.ndarray,
                       link_budget_model: bool,
                       debug_plots: bool,
                       grid_func,
                       **kwargs):
    """
    Docstring for process_drone_mesh:

    Inputs:
    --------
    grid_prefix: str, Name prefix used for plot titles, file names, and folders for a given grid type.
    wireless_prefix: str, Default = ""
    dist_comm: float, Communication distance of drones in meters.
    dim: tuple[float, float], Dimensions [x, y] of the area to be covered by the drone mesh.
    drone_height: float, Altitude (z-axis) of the drones in meters.
    tolerances: np.ndarray, Array of distance tolerances.
    drone_distance_redundancy: float, Redundancy factor applied to drone spacing calculation.
    dropout_rates: np.ndarray, Array of dropout percentages (0–1) for simulating partial mesh scenarios.
    dropout_iters: int, Number of iterations per dropout rate (used for histograms and statistics).
    margin_loss_db: float, Margin loss in dB for link calculations.
    device_grid: np.ndarray, Positions of devices to calculate drone-to-device connectivity.
    link_budget_model: bool, If True, use lookup-table-based link budget; otherwise use calculated link model.
    debug_plots: bool, If True, generates and saves detailed plots (histograms, drone positions, links).
    grid_func: function, Function that generates drone positions for the specified grid type; must accept dim and dist as inputs.
    **kwargs: dict, Additional keyword arguments passed to grid_func.

    Returns:
    --------
    None, Saves full and partial drone mesh outputs including:
    - Drone position plots (.png) for full and partial meshes.
    - Histograms of drone link counts (.png) for full and partial meshes.
    - Drone network graphs (.json) for full and partial meshes.
    - Link matrices (.tex) for LaTeX visualization.
    - Updates metadata.json with drone statistics, connectivity percentages, dropout rates, and number of drones.
    """

    # Create folder structure for mesh output
    #
    # ./<grid_prefix>_mesh_design_out/
    # |
    # |-- metadata.json
    # |
    # |-- full/
    # |   |-- plots/    -> Plots for the complete drone mesh
    # |   |               (full connectivity, histograms, device links, etc.)
    # |   |
    # |   `-- json/     -> JSON network files for the full mesh
    # |                   (nodes and links structure)
    # |
    # `-- partial/
    #     |-- plots/    -> Plots for dropout scenarios
    #     |               (histograms, example partial meshes, etc.)
    #     |
    #     `-- json/     -> JSON network files for partial meshes
    #                     (after drone removal)

    dir_origin = f"./{grid_prefix}_mesh_design_out"
    dir_origin_full_json = os.path.join(dir_origin, "full/json/")
    dir_origin_partial_json = os.path.join(dir_origin, "partial/json/")

    # Chech if output is valid else make it
    os.makedirs(dir_origin, exist_ok=True)
    os.makedirs(dir_origin_full_json, exist_ok=True)
    os.makedirs(dir_origin_partial_json, exist_ok=True)

    if debug_plots == True:
        dir_origin_full_plots = os.path.join(dir_origin, "full/plots/")
        dir_origin_partial_plots = os.path.join(dir_origin, "partial/plots/")

        os.makedirs(dir_origin_full_plots, exist_ok=True)
        os.makedirs(dir_origin_partial_plots, exist_ok=True)
        
    data_rate_Mbps = metadata[f"{wireless_prefix}DATA_RATE"] 
    bandwidth_Mhz = metadata[f"{wireless_prefix}BANDWIDTH"]

    # For plotting parameters set in Mbps
    thresholds_phyrate_heatmap = [data_rate_Mbps,20, 13, 3.3]
    # both for creation of json and also of plotting individual node links
    # plot individual node
    threshold_phyrate_links = 0
    # threshold for link to add to json 
    threshold_link_mbps = threshold_phyrate_links

    # For loop over number of tolerances
    for i in range(len(tolerances)):

        tolerance = tolerances[i]
        # Calculate distance from wireless communication range and tolerances
        drone_distance = distance_calc(dist_comm, tolerance, drone_distance_redundancy)

        # Choose grid function
        all_drone_positions = grid_func(dim=dim, dist=drone_distance, **kwargs)

        z_row = np.full((all_drone_positions.shape[0], 1), drone_height)
        all_drone_positions = np.hstack((all_drone_positions, z_row))

        # For loop over number of dropouts
        bar_dropout_rates = tqdm(dropout_rates)
        for j, dropout_rate in enumerate(bar_dropout_rates):
            bar_dropout_rates.set_description(f"Processing {grid_prefix} mesh tol={tolerance} | all dropout rates {dropout_rates} | current dropout={dropout_rate:.2f}")

            # Iterate over dropout rates and add to metadata
            #dropout_rate = dropout_rates[j]
            metadata[f"{grid_prefix}_{j}_DROPOUT_RATE"] = dropout_rate

            # Create array for total number of link count for dropout networks
            total_link_count_dropout = []
            total_link_count_dropout_cmd = []
            # Create variable for network is fully connected percentage
            total_reachable_phyrate = 0
            reachable_phyrates = []

            # For loop over dropout iterations for histogram
            for i in range(dropout_iters):
                drone_positions_dropout = dropout_drones(meta_prefix=f"{grid_prefix}_{j}_", drone_positions=all_drone_positions, dropout_rate=dropout_rate)
                
                # Make node and link list for partial drone mesh with removed drones
                node_list_dropout = node_list(drone_positions=drone_positions_dropout)
                link_list_dropout, link_count_dropout,link_count_dropout_cmd = link_list(wireless_prefix=wireless_prefix,
                                                                  nodes=node_list_dropout,
                                                                  dist_comm=dist_comm,
                                                                  margin_loss_db= margin_loss_db,
                                                                  eta=metadata["ETA_STRICT"],
                                                                  snr_eff=metadata["SNR_EFF_STRICT"],
                                                                  threshold_link=threshold_link_mbps,
                                                                  use_lookup_table=link_budget_model)

                # Make array of all link counts for partial drone mesh
                total_link_count_dropout.append(link_count_dropout)
                total_link_count_dropout_cmd.append(link_count_dropout_cmd)
                # Check if the remaining network after dropout is fully connected
                if debug_plots == True:
                    reachable_phyrate = checking_max_phyrate_fully_connected(nodes=node_list_dropout,dist_comm=dist_comm, base_rate= data_rate_Mbps, use_lookup_table=link_budget_model)
                    total_reachable_phyrate = total_reachable_phyrate + reachable_phyrate
                    reachable_phyrates.append(reachable_phyrate)

            if debug_plots == True:
                # Calculate the connected percentage of given dropout mesh
                metadata[f"{grid_prefix}_{j}_FULLY_CONNECTED_PHYRATE_AVERAGE"] = total_reachable_phyrate / dropout_iters
                metadata[f"{grid_prefix}_{j}_FULLY_CONNECTED_PHYRATE_MIN"] = min(reachable_phyrates)
                metadata[f"{grid_prefix}_{j}_FULLY_CONNECTED_PHYRATE_MAX"] = max(reachable_phyrates)

            # Metaprefix for file names
            prefix_dropout_real_perc = metadata[f"{grid_prefix}_{j}_DROPOUT_REAL_PERCENTAGE"]

            # Make single network of each dropout rate
            make_json_network(file_name=f"{grid_prefix}_network_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz.json",
                              file_folder_path=dir_origin_partial_json,
                              nodes=node_list_dropout,
                              links=link_list_dropout)

            # Calculating links from devices to drones for partial drone mesh
            if debug_plots == True:
                dist_device_to_drone= calculate_device_links(meta_prefix= f"{grid_prefix}_{j}_DROPOUT_",
                                    nodes=node_list_dropout,
                                    dist_comm=dist_comm,
                                    device_positions=device_grid)

                # Histogram and drone position plots over total iterations
                video_rate= metadata["histogram_high_rate"]
                cmd_rate= metadata["histogram_low_rate"]
                plot_histogram_drone_links(file_name=f"{grid_prefix}_video_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_histogram.png",
                                                title_name=f"{grid_prefix} Video {video_rate} Mbps Histogram | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                                                drone_link_count=total_link_count_dropout,
                                                iterations=dropout_iters,
                                                file_folder_path=dir_origin_partial_plots)
                plot_histogram_drone_links(file_name=f"{grid_prefix}_command_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_histogram.png",
                                                title_name=f"{grid_prefix} Command {cmd_rate} Mbps Histogram | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                                                drone_link_count=total_link_count_dropout_cmd,
                                                iterations=dropout_iters,
                                                file_folder_path=dir_origin_partial_plots)

                plot_drone_positions(meta_prefix=f"{grid_prefix}_{j}_DROPOUT_",
                                    wireless_prefix = wireless_prefix,
                                    file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_mesh.png",
                                    title_name=f"{grid_prefix} Mesh | Dropout = {prefix_dropout_real_perc*100:.2f}% | Tolerance = {tolerance} [m]",
                                    nodes=node_list_dropout,
                                    device_positions=device_grid,
                                    distance=drone_distance,
                                    dist_comm=dist_comm,
                                    thresholds_phyrate = thresholds_phyrate_heatmap,
                                    dist_device_to_drone=dist_device_to_drone,
                                    links=link_list_dropout,
                                    eta=metadata["ETA_STRICT"],
                                    snr_eff=metadata["SNR_EFF_STRICT"],
                                    dim= dim,
                                    file_folder_path=dir_origin_partial_plots,
                                    use_lookup_table=link_budget_model)
                plot_drone_links(title_name=f"{grid_prefix} Mesh | Dropout = {prefix_dropout_real_perc*100:.2f}% | Tolerance = {tolerance} [m]",
                                file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_links.png",
                                nodes=node_list_dropout,
                                links=link_list_dropout,
                                source_node="n0",
                                threshold_phyrate_links= threshold_phyrate_links,
                                file_folder_path=dir_origin_partial_plots)
                link_matrix(links=link_list_dropout,
                            nodes=node_list_dropout,
                            file_folder_path=dir_origin_partial_plots,
                            file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.2f}_dropout_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_Matrix")

        # Make node and link list for full drone mesh
        node_list_all = node_list(drone_positions=all_drone_positions)
        link_list_all, link_count_all,link_count_all_cmd = link_list(wireless_prefix=wireless_prefix,
                                                  nodes=node_list_all,
                                                  dist_comm=dist_comm,
                                                  margin_loss_db= margin_loss_db,
                                                  eta=metadata["ETA_STRICT"],
                                                  snr_eff=metadata["SNR_EFF_STRICT"],
                                                  threshold_link=threshold_link_mbps,
                                                  use_lookup_table=link_budget_model)

        # Add number drones used in full mesh to metadata
        metadata[f"{grid_prefix}_ALL_NUMBER_DRONES"] = len(node_list_all)

        # Make the json network from list of nodes
        make_json_network(file_name=f"{grid_prefix}_network_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz.json",
                          file_folder_path=dir_origin_full_json,
                          nodes=node_list_all,
                          links=link_list_all)

        if debug_plots == True:
            # Calculating links from devices to drones for full drone mesh
            dist_device_to_drone_full = calculate_device_links(meta_prefix=f"{grid_prefix}_ALL_",
                                nodes=node_list_all,
                                dist_comm=dist_comm,
                                device_positions=device_grid)

            # Histogram and drone position plots over full drone mesh
            plot_histogram_drone_links(file_name=f"{grid_prefix}_video_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_histogram.png",
                                        title_name=f"{grid_prefix} Video {video_rate} Mbps Histogram | tolerance = {tolerance} [m]",
                                        drone_link_count=link_count_all,
                                        file_folder_path=dir_origin_full_plots)
            plot_histogram_drone_links(file_name=f"{grid_prefix}_command_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_histogram.png",
                                        title_name=f"{grid_prefix} Command {cmd_rate} Mbps Histogram | tolerance = {tolerance} [m]",
                                        drone_link_count=link_count_all_cmd,
                                        file_folder_path=dir_origin_full_plots)
            
            plot_drone_positions(meta_prefix=f"{grid_prefix}_ALL_",
                                wireless_prefix=wireless_prefix,
                                file_name=f"{grid_prefix}_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_mesh.png",
                                title_name=f"{grid_prefix} Mesh | Tolerance = {tolerance} [m]",
                                nodes=node_list_all,
                                device_positions=device_grid,
                                distance=drone_distance,
                                dist_comm=dist_comm,
                                thresholds_phyrate = thresholds_phyrate_heatmap,
                                dist_device_to_drone=dist_device_to_drone_full,
                                links=link_list_all,
                                eta=metadata["ETA_STRICT"],
                                snr_eff=metadata["SNR_EFF_STRICT"],
                                dim= dim,
                                file_folder_path=dir_origin_full_plots,
                                use_lookup_table=link_budget_model)
            
            plot_drone_links(title_name=f"{grid_prefix} Mesh | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                            file_name=f"{grid_prefix}_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_links.png",
                            nodes=node_list_all,
                            links=link_list_all,
                            source_node="n0",
                            threshold_phyrate_links=threshold_phyrate_links,
                            file_folder_path=dir_origin_full_plots)
            link_matrix(links=link_list_all,
                        nodes=node_list_all,
                        file_folder_path=dir_origin_full_plots,
                        file_name=f"{grid_prefix}_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_Matrix")

    with open(os.path.join(dir_origin, "metadata.json"), "w") as f:
        json.dump(metadata, f)

def inputs_define(*,
        test_grid_meta_prefix,
        wireless_prefix: str = '',
        lookup_table,
        lookup_table_name,
        metadata,
        freq_Mhz,
        enable_graph_plots: bool = True):

    """
    Docstring for inputs_define:

    Inputs:
    --------
    test_grid_meta_prefix: str, Prefix for naming plots, folders, and output files for the mesh design.
    wireless_prefix: str, Optional prefix for wireless metadata keys (e.g., "HALOW_").
    lookup_table: dict, Lookup table containing modulation schemes with data rates, transmit powers, and receive sensitivities.
    lookup_table_name: str, Name of the lookup table (used for labeling in plots).
    metadata: dict, Dictionary storing system parameters and communication settings; will be updated in this function.
    freq_Mhz: float, Operating frequency in MHz used for link budget calculations.
    enable_graph_plots: bool, If True, generates sensitivity and range vs PHY rate plots.

    Returns:
    --------
    dist_comm: float, Calculated communication distance based on chosen data rate, transmit power, and receive sensitivity.
    use_lookup_table: bool, True if datasheet lookup table is used for link budget; False if modified Shannon model is used.
    """
    
    metadata["FREQ_MHZ"] = freq_Mhz

    available_bandwidth = list(lookup_table.keys())
    while True:
        print(f"Bandwidth possibilities {available_bandwidth}")

        desired_bandwidth_Mhz = int(input("Bandwidth: "))
        print()

        if desired_bandwidth_Mhz not in available_bandwidth:
            print(f"WARNING: Bandwidth possibilities are: {available_bandwidth}. NOT: {desired_bandwidth_Mhz}")
            print()
        else:
            break

    graph_sensitivity_phyrate(
        metadata=metadata,
        file_folder_path=f"./{test_grid_meta_prefix}_mesh_design_out/graph",
        filename=f"sensivity_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
        lookup_table=lookup_table,
        lookup_table_name=lookup_table_name,
        enable_plot=enable_graph_plots
    )

    graph_range_phyrate(
        metadata=metadata,
        file_folder_path=f"./{test_grid_meta_prefix}_mesh_design_out/graph",
        filename=f"range_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
        lookup_table=lookup_table,
        lookup_table_name=lookup_table_name,
        enable_plot=enable_graph_plots
    )
    while True:
        print("Possible link budget models:")
        print("1 = Datasheet ")
        print("2 = Modified Shannon")
        link_budget_model = int(input("Choice of link budget model: "))
        print()

        if link_budget_model in (1,2):
            break
        else:
            print(f"Warning: NOT AN LINK BUDGET OPTION: {link_budget_model}")
            print()

    if link_budget_model== 1:

        schemes = lookup_table[desired_bandwidth_Mhz]
        data_rates = [v["data_rate"] for v in schemes.values()]

        while True:
            print("Transmit power is automatically chosen as datasheet is chosen ")
            print(f"Datasheet datarates are {data_rates} Mbps")
            data_rate_Mbps = float(input("Choice data rate: "))
            print()

            if data_rate_Mbps not in data_rates:
                        print(f"Warning: NOT AN DATA RATE IN DATASHEET IN WIFI_HALOW_MM8108: {data_rate_Mbps} Mbps")
                        print()
            else:
                break

        get_halow_module_MM8108_params(
            metadata = metadata,
            wireless_prefix=wireless_prefix,
            desired_bandwidth_Mhz=desired_bandwidth_Mhz,
            desired_rate_Mbps=data_rate_Mbps,
            lookup_table = lookup_table)
        
        use_lookup_table = True

    elif link_budget_model== 2:

        data_rate_Mbps = float(input("Choice data rate: "))
        transmit_power_dbm = float(input("Choice transmit power: "))
        print() 
        metadata[f"{wireless_prefix}TRANSMIT_POWER"] = transmit_power_dbm

        shannon_mod_receive_sens_strict = shannon(
            metadata=metadata,
            data_rate_Mbps=data_rate_Mbps,
            bandwidth_Mhz=desired_bandwidth_Mhz,
            noise_figure_db=3,
            eta=metadata["ETA_STRICT"],
            snr_eff=metadata["SNR_EFF_STRICT"],
            wireless_prefix=wireless_prefix
        )

        use_lookup_table = False

    dist_comm = dist_comm_calc(
        transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
        received_power_dbm=metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"],
        freq_Mhz=freq_Mhz,
        margin_loss_db=metadata["MARGIN_LOSS"]
    )

    return dist_comm,use_lookup_table

def argument_define(*,
                    test_grid_meta_prefix: str,
                    wireless_prefix: str = '',
                    lookup_table: dict,
                    lookup_table_name: str,
                    desired_bandwidth_Mhz: float,
                    data_rate_Mbps: float,
                    freq_Mhz: float,
                    enable_graph_plots: bool = True,
                    link_budget_model: str,
                    transmit_power_dbm: float
                    ):

    """
    Docstring for argument_define:

    Inputs:
    --------
    test_grid_meta_prefix: str, Prefix for naming plots, folders, and output files for the mesh design.
    wireless_prefix: str, Optional prefix for wireless metadata keys (e.g., "HALOW_").
    lookup_table: dict, Lookup table containing modulation schemes with data rates, transmit powers, and receive sensitivities.
    lookup_table_name: str, Name of the lookup table (used for labeling in plots).
    desired_bandwidth_Mhz: float, Desired bandwidth in MHz used to select the closest scheme from the lookup table.
    data_rate_Mbps: float, Desired PHY rate in Mbps for link budget calculations.
    freq_Mhz: float, Operating frequency in MHz used for link budget calculations.
    enable_graph_plots: bool, If True, generates sensitivity vs PHY rate and range vs PHY rate plots.
    link_budget_model: str, Either "shannon" to use modified Shannon model or "datasheet" to use lookup table values.
    transmit_power_dbm: float, Transmit power in dBm to use with Shannon model (ignored if using datasheet model).

    Returns:
    --------
    dist_comm: float, Calculated communication distance based on chosen data rate, transmit power, and receive sensitivity.
    use_lookup_table: bool, True if datasheet lookup table is used for link budget; False if modified Shannon model is used.
    """
    
    metadata["FREQ_MHZ"] = freq_Mhz

    available_bandwidth = list(lookup_table.keys())
    if desired_bandwidth_Mhz not in available_bandwidth:
        print(f"WARNING: Bandwidth possibilities are: {available_bandwidth}. NOT: {desired_bandwidth_Mhz}")
        exit()

    graph_sensitivity_phyrate(
    metadata=metadata,
    file_folder_path=f"./{test_grid_meta_prefix}_mesh_design_out/graph",
    filename=f"sensivity_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
    desired_bandwidth_Mhz=desired_bandwidth_Mhz,
    lookup_table=lookup_table,
    lookup_table_name = lookup_table_name,
    enable_plot=enable_graph_plots
    )

    graph_range_phyrate(
        metadata=metadata,
        file_folder_path=f"./{test_grid_meta_prefix}_mesh_design_out/graph",
        filename=f"range_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
        lookup_table=lookup_table,
        lookup_table_name = lookup_table_name,
        enable_plot=enable_graph_plots
    )
    if link_budget_model == "shannon":
        metadata[f"{wireless_prefix}TRANSMIT_POWER"] = transmit_power_dbm

        if transmit_power_dbm is None:
            print(f"WARNING: TRANSMIT POWER IS NOT SET WHICH IS NECESSARY FOR SHANNON")
            print()
            exit()

        shannon_mod_receive_sens_strict = shannon(
            metadata=metadata,
            data_rate_Mbps=data_rate_Mbps,
            bandwidth_Mhz=desired_bandwidth_Mhz,
            noise_figure_db=3,
            eta=metadata["ETA_STRICT"],
            snr_eff=metadata["SNR_EFF_STRICT"],
            wireless_prefix=wireless_prefix
        )
        use_lookup_table = False

    elif link_budget_model == "datasheet":
        schemes = lookup_table[desired_bandwidth_Mhz]
        data_rates = [v["data_rate"] for v in schemes.values()]
        if data_rate_Mbps not in data_rates:
            print(f"Warning: {data_rate_Mbps} Mbps IS NOT A DATA RATE IN {lookup_table_name} DATASHEET FOR {desired_bandwidth_Mhz} MHz")
            data_rate_Mbps = min(data_rates, key=lambda x: abs(x - data_rate_Mbps))
            print(f"CHANGED TO CLOSEST VALID RATE OF: {data_rate_Mbps} Mbps ")
            print()

        get_halow_module_MM8108_params(
        metadata = metadata,
        wireless_prefix=wireless_prefix,
        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
        desired_rate_Mbps=data_rate_Mbps,
        lookup_table = lookup_table
        )
        use_lookup_table = True
        
        actually_transmitpower = metadata[f"{wireless_prefix}TRANSMIT_POWER"]
        if transmit_power_dbm is not None and actually_transmitpower != transmit_power_dbm:
            print(f"WARNING: TRANSMIT POWER WILL NOT BE USED, BECAUSE ALREADY SPECIFIED FROM DATASHEET: {transmit_power_dbm} Instead set to {actually_transmitpower}")
            print()
        if actually_transmitpower == transmit_power_dbm:
            print(f"WARNING: TRANSMIT POWER WILL NOT BE USED, HOWEVER YOU LUCKY, BECAUSE IT'S THE SAME AS: {actually_transmitpower}")
            print()
    else:
        print(f"Warning: NOT A LINK BUDGET OPTION: {link_budget_model}")
        exit()

    dist_comm = dist_comm_calc(
            transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
            received_power_dbm=metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"],
            freq_Mhz=freq_Mhz,
            margin_loss_db=metadata["MARGIN_LOSS"]
        )
    return dist_comm,use_lookup_table      

def main():
    parser = argparse.ArgumentParser(
        description="Example CLI",
        formatter_class=argparse.RawTextHelpFormatter  # <- preserves newlines
        )
    
    parser.add_argument("-g", "--grid", type=str, default=None,
                        help="Grid type: square or triangle")
    
    parser.add_argument("-d","--debugplots", action="store_true",
                        help="Enable debug plots")
    
    parser.add_argument("-w", "--wifi", type=str, default=None,
                        help="Wifi module: halow or 7")
    
    parser.add_argument("-b","--bandwidth", type = float, 
                        help = "WiFi halow options: [2, 4, 8], WIFI 7 options: [20]")
    
    parser.add_argument("-l","--link_budget", type = str, 
                        help = "Link budget models: Modified Shannon = shannon, Module datasheet = datasheet")
    
    parser.add_argument("-r", "--datarate", type=float, help="If choosing Modified Shannon all options are available but also need to specify -transmitpower.\n"
                                                             "WiFi Halow datasheet, 2 MHz: Only [0.7, 1.4, 2.2, 2.9, 4.3, 5.8, 6.5, 7.2, 8.9] Mbps available\n"
                                                             "WiFi Halow datasheet, 4 MHz: Only [1.5, 2.0, 4.5, 6.0, 9.0, 12, 14, 15, 18] Mbps available\n"
                                                             "WiFi Halow datasheet, 8 MHz: Only [3.3, 6.5, 9.8, 13, 20, 26, 29, 33, 39, 43] Mbps available\n"
                                                             "WiFi 7 datasheet: Only [6.5, 13, 19.5, 26, 39, 52, 58.5, 65, 78] Mbps available")
    
    parser.add_argument("-t","--transmitpower",type=float, 
                        help ="Only possible/necessary if using Shannon link budget")
    
    parser.add_argument("-tol","--tolerances", type = str,
                        help = "Set tolerances: Single value like 10 or comma-separated like 10,20,30. Default = 10")
    
    parser.add_argument("-drop","--dropout_rates", type = str,
                        help = "Set dropout rates: Single value like 10 or comma-separated like 10,20,30. Default = 0.05, 0.1, 0.15, 0.2")
    
    parser.add_argument("-iter","--iterations", type = int,
                        help = "Set amount of times each Dropout is ran. Default = 100 ")

    args = parser.parse_args()

    ###############################################################################
    #__________________________ TEST PARAMETERS __________________________________#
    ###############################################################################
    # dimensions of area
    length = 30000
    width = 10000
    drone_height = 500
    device_height = 5000
    scale_factor = 1
    test_dim = (length*scale_factor, width*scale_factor)
    test_samples = (30, 10)                                 # number of sample points on area (x, y)

    default_tolerances = np.arange(10, 15, 5)               # tolerance in meters (min, max, stepsize) 
    test_dist_redundancy = 0                                # distance redundancy for drone placement
    default_dropout_rates = np.arange(0.05,0.20,0.05)       # dropout rate in percentage (min, max, stepsize)
    default_drop_iter = 100                                 # number of iterations for each dropout rate (used for histogram)

    # wireless communication parameters for MM8108-MF15457 lookup table
    wireless_prefix = ""

    # safety variable for "other" losses
    margin_loss_db = 3 

    # Set grid type to process
    # if hexagonal grid is chosen bool variable extra_edge_drones
    # has to be set in function process_drone_mesh
    test_grid_meta_prefix = "Square"
    test_grid_func = drone_sq_grid

    ###############################################################################
    ###############################################################################

    # Save test parameters to metadata
    metadata["AREA_DIMENSIONS"] = str(test_dim)
    metadata["DRONE_HEIGHT"] = drone_height
    metadata["DEVICE_HEIGHT"] = device_height
    metadata["SAMPLES"] = str(test_samples)
    metadata["DISTANCE_REDUNDANCY"] = test_dist_redundancy

    #metadata["FREQ_MHZ"] = freq_Mhz
    # metadata[f"{wireless_prefix}TRANSMIT_POWER"] = transmit_power_dbm
    metadata["MARGIN_LOSS"] = margin_loss_db

    # Save dropout iterations used for histogram
    metadata["TOLERANCES"] = str(default_tolerances)
    metadata["DROPOUT_RATES"] = str(default_dropout_rates)
    metadata["DROPOUT_ITERATIONS"] = default_drop_iter

    # Calculate values for modelling wireless commmunication from wifi halow module
    # These values are the same for all grid types

    if all(value is None or value is False for value in vars(args).values()):
        while True:
            print("Choose Grid Type")
            print("1 = Square")
            print("2 = Triangle")
            grid = int(input("Enter number: "))
            print()

            if grid == 1:
                test_grid_meta_prefix = "Square"
                test_grid_func = drone_sq_grid
                break
            elif grid == 2:
                test_grid_meta_prefix = "Triangle"
                test_grid_func = drone_triangle_grid
                break
            else:
                print(f"Warning: NOT A GRID TYPE: {grid}")
                print()

        while True:
            print("Choose WiFi scheme:")
            print("1 = WiFi 7 ")
            print("2 = WiFi Halow")
            wifi_module = int(input("Enter number: "))
            print()

            if wifi_module in (1,2):
                break
            else: 
                print(f"Warning: NOT A AVAILABLE WIFI MODULE: {wifi_module}")
                print()

        while True:
            print("Desire of Debug Plots")
            print("1 = Only JSON File")
            print("2 = JSON File and Debug Plots")
            debug_int= int(input("Enter number: "))
            Enable_debug_plots = (debug_int == 2)
            print()

            if debug_int in (1,2):
                break
            else:
                print(f"WARNING: NEED TO SET DEBUG PLOT OFF (1) OR ON (2): NOT {debug_int}")
                print()

        if wifi_module == 1:
            dist_comm,use_lookup_table = inputs_define(test_grid_meta_prefix = test_grid_meta_prefix,
                        wireless_prefix=wireless_prefix,
                        lookup_table=lookup_table_wifi7_eht_GI0_8_OFDM,
                        lookup_table_name = "WIFI_7_GI0_8_OFDM",
                        metadata=metadata,
                        freq_Mhz = 6000,
                        enable_graph_plots=Enable_debug_plots)


        elif wifi_module == 2:
            dist_comm,use_lookup_table = inputs_define(test_grid_meta_prefix = test_grid_meta_prefix,
                        wireless_prefix=wireless_prefix,
                        lookup_table=lookup_table_halow_module_MM8108,
                        lookup_table_name = "WIFI_HALOW_MM8108",
                        metadata=metadata,
                        freq_Mhz = 868,
                        enable_graph_plots=Enable_debug_plots)

    else:
        grid = args.grid.strip().lower() if args.grid else None
        wifi_module = args.wifi.strip().lower() if args.wifi else None
        Enable_debug_plots = args.debugplots
        desired_bandwidth_Mhz = args.bandwidth
        link_budget_model = args.link_budget.strip().lower() if args.link_budget else None
        data_rate_Mbps = args.datarate
        transmit_power_dbm = args.transmitpower
        tol = args.tolerances
        dropout_iter = args.iterations
        drop_rates = args.dropout_rates
        if tol is not None:
            default_tolerances = np.array([float(x) for x in tol.split(",")])
        if dropout_iter is not None:
            default_drop_iter = dropout_iter
        if  drop_rates is not None:
            default_dropout_rates = np.array([float(x) for x in drop_rates.split(",")])
            for i in range(len(default_dropout_rates)):
                rate = default_dropout_rates[i]
                if rate > 1 and rate <= 100:
                    print()
                    print(f"WARNING: dropout rate {rate} is not in range 0 to 1")
                    default_dropout_rates[i] = rate / 100
                    print(f"EXPECTED: you meant to write {default_dropout_rates[i]}")
                if rate > 100:
                    print()
                    print(f"WARNING: THE RATES ARE SUPPORTED FOR 0.0 to 1.0, {rate} IS NOT WITHIN RANGE")
                    exit()

        metadata["TOLERANCES"] = str(default_tolerances)
        metadata["DROPOUT_RATES"] = str(default_dropout_rates)
        metadata["DROPOUT_ITERATIONS"] = default_drop_iter
        print()
        if grid == "square":
            test_grid_meta_prefix = "Square"
            test_grid_func = drone_sq_grid
        elif grid == "triangle":
            test_grid_meta_prefix = "Triangle"
            test_grid_func = drone_triangle_grid
        else:
            print(f"Warning: NOT A GRID TYPE: {grid}")
            print()
            exit()

        if wifi_module == "halow":
            freq_Mhz = 868
            dist_comm,use_lookup_table = argument_define(test_grid_meta_prefix=test_grid_meta_prefix,
                                                        wireless_prefix='',
                                                        lookup_table=lookup_table_halow_module_MM8108,
                                                        lookup_table_name="WIFI_HALOW_MM8108",
                                                        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
                                                        data_rate_Mbps= data_rate_Mbps,
                                                        freq_Mhz=freq_Mhz,
                                                        enable_graph_plots=Enable_debug_plots,
                                                        link_budget_model=link_budget_model,
                                                        transmit_power_dbm=transmit_power_dbm)
        elif wifi_module == "7":
            freq_Mhz = 6000
            dist_comm,use_lookup_table = argument_define(test_grid_meta_prefix=test_grid_meta_prefix,
                                                        wireless_prefix='',
                                                        lookup_table=lookup_table_wifi7_eht_GI0_8_OFDM,
                                                        lookup_table_name="WIFI_7_GI0_8_OFDM",
                                                        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
                                                        data_rate_Mbps= data_rate_Mbps,
                                                        freq_Mhz=freq_Mhz,
                                                        enable_graph_plots=Enable_debug_plots,
                                                        link_budget_model=link_budget_model,
                                                        transmit_power_dbm=transmit_power_dbm)
        else:
            print(f"Warning: NOT AN AVAILABLE WIFI MODULE: {wifi_module}")
            exit()

    print(f"The range is calculate to be {dist_comm} [m]")
    if use_lookup_table == True:
        print()
        print("Warning: using rounded to reference thresholds from lookup table")

    # Both a device_grid and a device_point can be used in process_drone_mesh
    device_point = np.array([[100,100,device_height]])
    device_grid = make_device_grid(dim=test_dim,
                                    z_height=device_height,
                                    sample_resolution=test_samples)

    # Process a drone mesh to give metadata and plots
    process_drone_mesh(grid_prefix=test_grid_meta_prefix,
                       wireless_prefix=wireless_prefix,
                       dist_comm=dist_comm,
                       dim=test_dim,
                       drone_height=drone_height,
                       tolerances=default_tolerances,
                       drone_distance_redundancy=test_dist_redundancy,
                       dropout_rates=default_dropout_rates,
                       dropout_iters=default_drop_iter,
                       margin_loss_db=margin_loss_db,
                       device_grid=device_grid,
                       link_budget_model = use_lookup_table,
                       debug_plots = Enable_debug_plots,
                       grid_func=test_grid_func
                    )

if __name__ == "__main__":
    main()
