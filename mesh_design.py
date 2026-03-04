import numpy as np
import matplotlib.pyplot as plt
import math
import os
from tqdm import tqdm
from collections import Counter
import json
from dataclasses import dataclass, asdict
from scipy.optimize import curve_fit


metadata = dict()

@dataclass
class Node:
    id: str
    x: int
    y: int

@dataclass
class Link:
    source: str
    target: str
    data_rate: str
    
###############################################################################
#__________________________ DRONE MESH GRIDS _________________________________#
###############################################################################
def make_grid_product(x_range, y_range):
    return np.stack(np.meshgrid(x_range, y_range), axis = -1).reshape(-1,2)

def drone_sq_grid(dim: tuple[float, float],
                  dist: float):
    
    x_dim, y_dim = dim

    col_num_drones = y_dim // dist
    center_dist = dist * col_num_drones
    offset =(y_dim - center_dist) /2

    x_range = np.arange(offset,x_dim+1, dist)   
    y_range = np.arange(offset,y_dim+1, dist)   

    return make_grid_product(x_range, y_range)
    
def drone_triangle_grid(dim: tuple[float, float],
                        dist: float):
    
    x_dim, y_dim = dim

    # Angle from node in full column to adjacent node in partial column relative to x axis
    alpha = np.radians(30) 

    full_col_num_drones = y_dim // dist

    center_dist = dist * full_col_num_drones
    offset =(y_dim - center_dist) /2
    
    # Calculate y locations for full columns
    full_cols_y_range = np.arange(offset, y_dim+1, dist)

    # Calculate number of full comlumns
    full_col_x_dist = 2*dist*np.cos(alpha)
    num_full_cols = math.ceil(x_dim / full_col_x_dist)+1

    full_cols_x_range = np.linspace(0, (num_full_cols-1)*full_col_x_dist, num=num_full_cols)
    full_col_pos = make_grid_product(full_cols_x_range, full_cols_y_range)

    # Calculate number of rows in partal columns
    part_col_num_rows = len(full_cols_y_range)-1

    # linspace(start, start + step*num, num=num, endpoint=False)
    part_cols_y_range = np.linspace(offset + dist*np.sin(alpha), 
                                    offset + dist*np.sin(alpha) + 2*dist*np.sin(alpha)*part_col_num_rows, 
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

def distance_calc(dist_comm: float, 
                  tolerance: float, 
                  dist_redundancy: float) -> float:

    distance = dist_comm - tolerance - dist_redundancy

    return distance
    
# Shannon for calculating received power (not in used due to datasheet is used instead)
def shannon(data_rate_Mbps: float, 
            bandwidth_Mhz: float = 4, 
            noise_figure_db: float = 6,
            snr_eff: float = 1,
            eta: float = 1) -> float:
    """
    default values:

    bandwidth = 5 MHz (bandwidth of wifi halow)
    noise_figure = 3db (double of ideal thermal noise) usually 3-5db
    transmit_power_dbm = 24dbm
    transmit_gain_dbi = 0 (isotropic) usually in range 0-3 dbi
    received_gain_dbi = 0 usually in range 0-3 dbi
    margin_loss_db = 2 dB (other losses like polarization mismatch)
    freq_mhz = 863 - 868 (wifi halow)
    snr_eff = 1 for standard shannon
    eta = 1 for standard shannon
    """


    # Calculate shannon 
    # data_rate_bps = bandwidth_hz * math.log2(1 + (signal_power/noise_power))
    # isolate snr
    data_rate_bps = data_rate_Mbps * 10**6 # convert datarate from Mpbs to bps
    bandwidth_hz = bandwidth_Mhz * 10**6 # convert bandwidth from Mhz to Hz

    bandwidth_eff_hz = eta * bandwidth_hz
    snr = 2**(data_rate_bps/bandwidth_eff_hz) - 1
    # adjust if desire modifed shannon
    snr /= snr_eff
    snr_db = 10* math.log10(snr)

    # Calculate noise power (-174 dbm/Hz is thermal noise density )
    noise_power_dbm = -174 + 10 * math.log10(bandwidth_eff_hz) + noise_figure_db

    # Calculate received power
    received_power_dbm = snr_db + noise_power_dbm

    return received_power_dbm

# Look up table for halow module MM8108-MF15457 values are (data_rate, received_sensitivity, transmit_power) 
lookup_table_halow_module_MM8108 = {
    2: {
        0: {"data_rate": 0.7,  "receive_sensitivity": -103, "transmit_power": 25.0},
        1: {"data_rate": 1.4, "receive_sensitivity": -101, "transmit_power": 25.0},
        2: {"data_rate": 2.2,  "receive_sensitivity": -99, "transmit_power": 25.0},
        3: {"data_rate": 2.9, "receive_sensitivity": -96, "transmit_power": 25.0},
        4: {"data_rate": 4.3,  "receive_sensitivity": -93, "transmit_power": 24.5},
        5: {"data_rate": 5.8, "receive_sensitivity": -89, "transmit_power": 23.0},
        6: {"data_rate": 6.5,  "receive_sensitivity": -87, "transmit_power": 21.5},
        7: {"data_rate": 7.2, "receive_sensitivity": -86, "transmit_power": 20.0},
        8: {"data_rate": 8.9,  "receive_sensitivity": -82, "transmit_power": 18.0},
    },

    4: {
        0: {"data_rate": 1.5,  "receive_sensitivity": -102, "transmit_power": 22.5},
        1: {"data_rate": 3.0, "receive_sensitivity": -99, "transmit_power": 22.5},
        2: {"data_rate": 4.5,  "receive_sensitivity": -97, "transmit_power": 22.5},
        3: {"data_rate": 6.0, "receive_sensitivity": -94, "transmit_power": 22.5},
        4: {"data_rate": 9.0,  "receive_sensitivity": -90, "transmit_power": 22.5},
        5: {"data_rate": 12, "receive_sensitivity": -86, "transmit_power": 21.5},
        6: {"data_rate": 14,  "receive_sensitivity": -85, "transmit_power": 20.5},
        7: {"data_rate": 15, "receive_sensitivity": -83, "transmit_power": 19.5},
        8: {"data_rate": 18,  "receive_sensitivity": -79, "transmit_power": 19.0},
        9: {"data_rate": 20, "receive_sensitivity": -78, "transmit_power": 17.0},
    },

    8: {
        0: {"data_rate": 3.3,  "receive_sensitivity": -98, "transmit_power": 22.5},
        1: {"data_rate": 6.5, "receive_sensitivity": -95, "transmit_power": 22.0},
        2: {"data_rate": 9.8,  "receive_sensitivity": -93, "transmit_power": 22.0},
        3: {"data_rate": 13, "receive_sensitivity": -90, "transmit_power": 22.0},
        4: {"data_rate": 20,  "receive_sensitivity": -87, "transmit_power": 22.0},
        5: {"data_rate": 26, "receive_sensitivity": -83, "transmit_power": 21.5},
        6: {"data_rate": 29,  "receive_sensitivity": -81, "transmit_power": 20.5},
        7: {"data_rate": 33, "receive_sensitivity": -80, "transmit_power": 20.0},
        8: {"data_rate": 39,  "receive_sensitivity": -76, "transmit_power": 19.0},
        9: {"data_rate": 43, "receive_sensitivity": -74, "transmit_power": 16.0},
    }
}

def get_halow_module_MM8108_params(*,
                                   wireless_prefix: str ="",
                                   desired_bandwidth_Mhz, 
                                   desired_rate_Mbps):
    # Find closest available bandwidth
    available_bandwidth = np.array(list(lookup_table_halow_module_MM8108.keys()))
    bandwidth_index = np.argmin(np.abs(available_bandwidth - desired_bandwidth_Mhz))
    closest_bandwidth = int(available_bandwidth[bandwidth_index])

    # Get all MCS schemes for that bandwidth
    schemes = lookup_table_halow_module_MM8108[closest_bandwidth].values()

    # Find the sorted_scheme with data_rate closest to desired_rate_Mbps
    sorted_schemes = sorted(schemes, key=lambda s: abs(s['data_rate'] - desired_rate_Mbps))

    metadata[f"{wireless_prefix}BANDWIDTH"] = closest_bandwidth

    # Find first sorted_scheme >= desired datarate
    for best_scheme in sorted_schemes:
        if best_scheme['data_rate'] >= desired_rate_Mbps:
            metadata[f"{wireless_prefix}DATA_RATE"] = best_scheme['data_rate']
            metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"] = best_scheme['receive_sensitivity']
            metadata[f"{wireless_prefix}TRANSMIT_POWER"] = best_scheme['transmit_power']
            break
        else:
            # If desired data rate above all availeble schemes return highest sorted_scheme
            best_scheme = sorted_schemes[0]
            metadata[f"{wireless_prefix}DATA_RATE"] = best_scheme['data_rate']
            metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"] = best_scheme['receive_sensitivity']
            metadata[f"{wireless_prefix}TRANSMIT_POWER"] = best_scheme['transmit_power']

def dist_comm_calc(transmit_power_dbm: float = 16, 
                   received_power_dbm: float = -74,
                   transmit_gain_dbi: float = 0, 
                   received_gain_dbi: float = 0,
                   margin_loss_db: float = 0, 
                   freq_Mhz: float = 868) -> float:
    """
    default values:
    
    transmit_power_dbm = 24dbm
    transmit_gain_dbi = 0 (isotropic) usually in range 0-3 dbi
    received_gain_dbi = 0 usually in range 0-3 dbi
    margin_loss_db = 2 dB (other losses like polarization mismatch)
    freq_mhz = 863 - 868 (wifi halow)
    """

    # Calculate free space path loss 
    fspl = transmit_power_dbm + transmit_gain_dbi + received_gain_dbi - received_power_dbm - margin_loss_db

    # Calculate communication distance 32.44 is unit conversion constant  
    # 32.44 = 20 log10(4pi/c) + 20 log10(10^3) + 20 log10(10^6)
    dist_comm_km = 10**((fspl - 20 * math.log10(freq_Mhz) - 32.44) / 20)
    
    dist_comm = dist_comm_km * 1000

    return dist_comm

def dropout_drones(*,
                   meta_prefix: str = "",
                   drone_positions: np.ndarray,
                   dropout_rate: float) -> np.ndarray:
    """
    Docstring for dropout_drones
    
    Inputs: 
    meta_prefix: prefix string prepended to metadata keys
    drone_positions: Nx2 numpy array (not mutated)
    dropout_rate: percentage of drones which are removed (0..1) 

    Returns: Mx2 numpy array of drones left after dropout. 
    Return array originates from copy of drone_positions.
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
    drone_positions_result = drone_positions_result[:-num_drones_dropout, :]
    
    # Writing stats to metadata
    metadata[f"{meta_prefix}DROPOUT_REAL_PERCENTAGE"] = drone_dropout_perc_real
    metadata[f"{meta_prefix}DROPOUT_NUM_DRONES"] = num_drones_dropout

    return drone_positions_result

def calculate_device_links(*,
                           meta_prefix: str = "",
                           nodes: list,
                           dim: tuple[float, float],
                           dist_comm: float,
                           sample_resolution: tuple[float, float]) -> np.ndarray:
    """
    Docstring for calculate_device_links
    
    Inputs:
    grid_name: Name of grid used for file and plot name
    nodes: List of nodes contataining of drone positions in a given mesh
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    sample_resolution: Sample resolution [x, y] ie. how many sample points inside the dimensions
    
    Returns: 
    Saves min and max device links to metadata
    Saves percentage of area covered to metadata
    """

    x_dim, y_dim = dim
    x_sample_res, y_sample_res = sample_resolution

    # Device points in drone area
    x_device = np.linspace(0, x_dim, x_sample_res)
    y_device = np.linspace(0, y_dim, y_sample_res)
    X_device, Y_device = np.meshgrid(x_device, y_device)

    # Flatten device grid -> shape (N_device, 2)
    device_positions = np.stack([X_device.ravel(), Y_device.ravel()], axis=1)

    # Extract drone position from list -> shape (N_points, 2)
    drone_positions = np.asarray([[node.x, node.y] for node in nodes])

    # Compute squared distances using broadcasting
    # device_points[:, None, :] -> (N_points, 1, 2)
    # drone_positions[None, :, :] -> (1, N_drones, 2)
    # Result -> (N_points, N_drones)
    diff = device_positions[:, None, :] - drone_positions[None, :, :]
    distances_sq = np.sum(diff**2, axis=2)

    # Count links per device point
    links_per_device = np.sum(distances_sq <= dist_comm**2, axis=1)

    # Saving min and mean in dict for drone plot
    metadata[f"{meta_prefix}MIN_DEVICE_LINKS"] = float(np.min(links_per_device))
    metadata[f"{meta_prefix}MEAN_DEVICE_LINKS"] = float(np.mean(links_per_device))

    # Area coverage percentage
    covered_points = np.sum(links_per_device > 0)
    total_points = links_per_device.size

    # Save area covered percentage to metadata
    metadata[f"{meta_prefix}AREA_COVERED"] = covered_points / total_points

def is_network_fully_connected(nodes: list[Node], 
                               links: list[Link]) -> bool:
    """
    Docstring for is_network_fully_connected

    Inputs:
    nodes: List of nodes contataining of drone positions in a given mesh
    links: List of drone links

    Returns:
    True if the network is fully connected.
    """

    # If no drones in network return true
    if len(nodes) == 0:
        return True

    # Build adjacency list 
    adjacency = {node.id: [] for node in nodes}

    # Add links to other nodes in both directions since network is undirected
    for link in links:
        adjacency[link.source].append(link.target)
        adjacency[link.target].append(link.source)

    # BFS algorithm
    start_node = nodes[0].id                    # Set start node
    visited = set([start_node])                 # Mark start node as visited, set([start_node]) = {start_node}
    queue = [start_node]                        # Place start node in queue to explore


    while queue:
        current = queue.pop(0)                  # Take next node in queue to explore
        for neighbor in adjacency[current]:     # Look at all drones connected to it
            if neighbor not in visited:         # If neighbor not visited it is new so
                visited.add(neighbor)           # Mark the new node as visited
                queue.append(neighbor)          # Add it to queue to explore later

    return len(visited) == len(nodes)

def shannon_inverse_bitrate(received_power_dbm: float = -74, 
                            bandwidth_Mhz: float = 8, 
                            noise_figure_db: float = 6,
                            snr_eff: float = 1,
                            eta: float = 1) -> float:
    
    bandwidth_hz = bandwidth_Mhz * 10**6 # convert bandwidth from Mhz to Hz
    bandwidth_eff_hz = eta * bandwidth_hz

    # Calculate noise power (-174 dbm/Hz is thermal noise density )
    noise_power_dbm = -174 + 10 * math.log10(bandwidth_eff_hz) + noise_figure_db
    
    # Linear SNR
    snr_linear = 10 ** ((received_power_dbm - noise_power_dbm) / 10)

    # Adjust for SNR efficiency
    snr_linear *= snr_eff

    # Shannon formula (bps)
    data_rate_bps = bandwidth_eff_hz * math.log2(1 + snr_linear)

    # Convert to Mbps
    data_rate_Mbps = data_rate_bps / 10**6

    return data_rate_Mbps
    
def sensivity_given_range_fspl(distance_m: float,
                                transmit_power_dbm: float = 22,
                                transmit_gain_dbi: float = 0, 
                                received_gain_dbi: float = 0,
                                margin_loss_db: float = 0, 
                                freq_Mhz: float = 868) -> float:
    # convert distance to km
    distance_km = distance_m / 1000
    # FSPL in dB
    fspl = 20 * math.log10(distance_km) + 20 * math.log10(freq_Mhz) + 32.44

    received_power_dbm = transmit_power_dbm + transmit_gain_dbi + received_gain_dbi - margin_loss_db - fspl

    return received_power_dbm

###############################################################################
#_____________________ NETWORK LISTS (JSON) __________________________________#
###############################################################################

def node_list(drone_positions: np.ndarray) -> list[Node]:

    """
    Docstring for node_list
    
    Inputs:
    drone_positions: Nx2 Numpy array of drone positions in a given mesh

    Returns:
    nodes: list of sorted N Node classes of drone IDs and positions
    """    

    # Sort drone positions by x then y
    sorted_pos_indences = np.lexsort((drone_positions[:,1],  #secondary key (y)
                                      drone_positions[:,0])) #primary key (x)
    
    drone_positions = drone_positions[sorted_pos_indences]

    x_pos = drone_positions[:,0]
    y_pos = drone_positions[:,1]

    nodes: list[Node] = []

    for i in range(len(drone_positions)):
        id = f"{x_pos[i]:.2f}_{y_pos[i]:.2f}"
        node = Node(id=id, x=float(x_pos[i]), y=float(y_pos[i]))
        nodes.append(node)
    
    return nodes

def link_list(*,
              wireless_prefix: str = "",
              nodes: list,
              dist_comm: float,
              margin_loss_db: float,
              eta: float = 0.79,
              snr_eff: float = 0.14) -> list[Link]:
    
    """
    Docstring for link_list
    
    Inputs:
    nodes: list of sorted N Node classes of drone IDs and positions
    dist_comm: Communication distance of drone in meters

    Returns:
    links: list of N Link classes with sources and respective targets
    num_links: Nx1 numpy array of links for each drone
    """    
    
    links: list[Link] = []
    num_links = [] 
    for source in nodes:
        count = 0
        for target in nodes:

            if target.id == source.id:
               continue
 
            # Compute distances from drone i to all drones
            distances = (target.x - source.x)**2 + (target.y - source.y)**2    

            # if distances <= (dist_comm + 1)**2:
            #predicted_rate= exp_model(np.sqrt(distances), scale_exp, exp_param)
            data_rate_mbps = data_rate_given_dist_comm(distance_m=np.sqrt(distances),
                                               bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                                               transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                                               margin_loss_db=margin_loss_db,
                                               eta=eta,
                                               snr_eff=snr_eff)
            link = Link(source=source.id, 
                        target=target.id,
                        data_rate=f"{data_rate_mbps:.2f}")
                    #   data_rate=str(metadata[f"{wireless_prefix}DATA_RATE"]))
            links.append(link)       

            if distances <= (dist_comm + 1)**2:
            # Count how many are within dist_comm (exclude itself)
                count = count + 1 
        
        num_links.append(count)
    return links, num_links

def make_json_network(*,
                      file_name: str,
                      file_folder_path: str,
                      nodes: list,
                      links: list):
    """
    Docstring for make_json_network


    """
    network = dict()

    network["nodes"] = [asdict(i) for i in nodes]
    network["links"] = [asdict(j) for j in links]

    with open(os.path.join(file_folder_path, file_name), "w") as f:
        json.dump(network, f)

###############################################################################
#___________________________ PLOT FUNCITONS __________________________________#
###############################################################################

def plot_drone_positions(*,
                         meta_prefix: str = "", 
                         title_name: str,
                         file_name: str,
                         nodes: list,
                         distance: float,
                         dist_comm: float,
                         drone_link_count: np.ndarray,
                         file_folder_path: str,
                         font_size: float = 8.0):
    
    fig, ax_drone_pos = plt.subplots()
    
    # Plot drone positions as dots form node list
    x_pos = [node.x for node in nodes]
    y_pos = [node.y for node in nodes]
    ax_drone_pos.plot(x_pos, y_pos, 'o', color = 'red', markersize=2)


    for _, node in enumerate(nodes):
        x = node.x
        y = node.y

        # Draw communcation dist_comm as circle
        circle = plt.Circle((x, y), dist_comm, fill=True, facecolor='blue', edgecolor='black', alpha=0.1)
        ax_drone_pos.add_patch(circle)

    device_links_min = metadata[f"{meta_prefix}MIN_DEVICE_LINKS"]
    device_links_mean = metadata[f"{meta_prefix}MEAN_DEVICE_LINKS"]

    title_text = (
    f"{title_name}\n"
    f"Drones = {len(nodes)}, d = {distance:.2f} [m], dist_comm = {dist_comm:.2f} [m] \n"
    f"Drone links: Min = {np.min(drone_link_count)}, Avg = {np.mean(drone_link_count):.2f}, Device links: Min = {device_links_min}, Avg = {device_links_mean:.2f}"
)
    ax_drone_pos.set_title(title_text, fontsize=font_size, fontweight='bold')
    ax_drone_pos.set_xlabel("[m]", fontsize=font_size)
    ax_drone_pos.set_ylabel("[m]", fontsize=font_size)
    ax_drone_pos.set_aspect('equal', 'box')
    ax_drone_pos.tick_params(axis='both', labelsize=font_size)

    file_path = os.path.join(file_folder_path, file_name)
    fig.savefig(file_path, dpi=300, bbox_inches='tight')
    
    plt.close(fig)

def plot_histogram_drone_links(*,
                               file_name: str,
                               title_name: str,
                               drone_link_count: list,
                               iterations: int = 1,
                               file_folder_path: str,
                               font_size: float = 8.0):

    # Build histogram of # drones and # links
    fig_hist, ax_hist = plt.subplots()

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
            va='bottom'
            )

    # Show only integer ticks (only existing values)
    ax_hist.set_xticks(range(np.max(x_values)+1))
    ax_hist.set_xlim(-0.5, np.max(x_values)+0.5)

    file_path_hist = os.path.join(file_folder_path, file_name)
    fig_hist.savefig(file_path_hist, dpi=300, bbox_inches='tight')
    plt.close(fig_hist)


def shannon_fit( data_rate, snr_eff, eta,bandwidth):
    # Use the closest_bandwidth (assume constant) and fixed noise figure
    return np.array([
        shannon(
            data_rate_Mbps=dr,
            bandwidth_Mhz=bandwidth,
            noise_figure_db=3,
            eta=eta,
            snr_eff=snr_eff
        ) 
        for dr in data_rate
    ])

def sort_scheme_for_data_rate(desired_bandwidth_Mhz):
    available_bandwidth = np.array(list(lookup_table_halow_module_MM8108.keys()))
    bandwidth_index = np.argmin(np.abs(available_bandwidth - desired_bandwidth_Mhz))
    closest_bandwidth = int(available_bandwidth[bandwidth_index])

    # Get all MCS schemes for that bandwidth
    schemes = lookup_table_halow_module_MM8108[closest_bandwidth].values()

    # Find the sorted_scheme with data_rate closest to desired_rate_Mbps
    sorted_schemes = sorted(schemes, key=lambda s: s['data_rate'])

    return sorted_schemes, closest_bandwidth

def graph_sensitivity_phyrate(desired_bandwidth_Mhz: float,
                              eta_strict: float = 0.79,
                              snr_eff_strict: float = 0.14
                              ):

    sorted_schemes, closest_bandwidth = sort_scheme_for_data_rate(desired_bandwidth_Mhz)

    # Take the values out from the lookup table
    data_rates = [s['data_rate'] for s in sorted_schemes]
    sensitivities = [s['receive_sensitivity'] for s in sorted_schemes]

    shannon_receive_sens = [
        shannon(
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3
        )
        for data_rate in data_rates
    ]

    # fir the best parameters for snr_eff and eta to fit the datasheet
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
   
    shannon_mod_receive_sens_optimal = [
        shannon(
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3,
            eta=0.77,
            snr_eff=0.17
        )
        for data_rate in data_rates
    ]

    shannon_mod_receive_sens_strict = [
        shannon(
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3,
            eta=eta_strict,
            snr_eff=snr_eff_strict 
        )
        for data_rate in data_rates
    ]
    # create plot
    fig, ax1 = plt.subplots()

    ax1.set_xlabel("Receive Sensitivity (dBm)")
    ax1.set_ylabel("Data Rate (Mbps)")
    ax1.plot(sensitivities, data_rates,'x', label="Datasheet MM8108",)
    ax1.plot(shannon_receive_sens, data_rates, label="Shannon")
    ax1.plot(shannon_mod_receive_sens_optimal, data_rates, label=f"Modified Shannon Optimized snr_eff: {snr_eff_opt:.2f}, eta: {eta_opt:.2f}")
    ax1.plot(shannon_mod_receive_sens_strict, data_rates, label=f"Modified Shannon Strict snr_eff: {snr_eff_strict}, eta: {eta_strict}")
    ax1.legend()
    plt.show() 

def data_rate_given_dist_comm(distance_m: float,
                              bandwidth_Mhz: float = 8,
                              transmit_power_dbm: float = 22,
                              margin_loss_db: float = 0,
                              eta: float = 0.79,
                              snr_eff: float = 0.14
                              ):
    required_sens= sensivity_given_range_fspl(distance_m=distance_m,
                               transmit_power_dbm=transmit_power_dbm,
                               transmit_gain_dbi= 0,
                               received_gain_dbi= 0,
                               margin_loss_db=margin_loss_db,
                               freq_Mhz=868)

    data_rate_Mbps = shannon_inverse_bitrate(received_power_dbm=required_sens,
                            bandwidth_Mhz=bandwidth_Mhz,
                            noise_figure_db= 3,
                            eta = eta,
                            snr_eff= snr_eff)
    return data_rate_Mbps

def graph_range_phyrate(desired_bandwidth_Mhz: float,
                        eta_strict: float = 0.79,
                        snr_eff_strict: float = 0.14):
    data_rates = []
    dist_comms = []

    sorted_schemes, closest_bandwidth = sort_scheme_for_data_rate(desired_bandwidth_Mhz)

    # Take the values out from the lookup table
    data_rates = [ s['data_rate'] for s in sorted_schemes]
    dist_comms= [ dist_comm_calc(s['transmit_power'],s['receive_sensitivity'],transmit_gain_dbi=0,received_gain_dbi=0,margin_loss_db=3,freq_Mhz=868) for s in sorted_schemes]
    
    shannon_mod_receive_sens_optimal = [
        shannon(
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3,
            eta=0.77,
            snr_eff=0.17
        )
        for data_rate in data_rates
    ]
    dist_comms_mod_shannon_optimal = [
        dist_comm_calc(
            s['transmit_power'],
            shannon_mod_receive_sens_optimal[i],   # use the corresponding receive sens
            transmit_gain_dbi=0,
            received_gain_dbi=0,
            margin_loss_db=3,
            freq_Mhz=868
        )
        for i, s in enumerate(sorted_schemes)
    ]
    shannon_mod_receive_sens_strict = [
        shannon(
            data_rate_Mbps=data_rate,
            bandwidth_Mhz=closest_bandwidth,
            noise_figure_db=3,
            eta=eta_strict,
            snr_eff=snr_eff_strict
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
            freq_Mhz=868
        )
        for i, s in enumerate(sorted_schemes)
    ]

    # FIGURE
    total_deviation = 0
    fig, ax1 = plt.subplots()
    plt.xscale('log')  # set x-axis to logarithmic
    ax1.set_xlabel("Range (m)")
    ax1.set_ylabel("Data Rate (Mbps)")
    ax1.plot(dist_comms, data_rates,'x', label="Datasheet MM8108")
    for x, y, z in zip(dist_comms, data_rates, dist_comms_mod_shannon_optimal):
        deviation = x - z            # residual
        ax1.annotate(f"Optimal \n ({x:.2f}, {y} \n Δ={deviation:.2f} Meter)",
                    (x, y),
                    textcoords="offset points",
                    xytext=(5, 5),  
                    fontsize=8)
        total_deviation += abs(deviation)
    avg_deviation = total_deviation / len(dist_comms)
    ax1.plot(dist_comms_mod_shannon_optimal, data_rates, label=f"Modified shannon MM8108 with avg deviation of {avg_deviation:.2f} Meter Optimal")
    for x, y, z in zip(dist_comms, data_rates, dist_comms_mod_shannon_strict):
        deviation = x - z            # residual
        ax1.annotate(f"Strict \n ({x:.2f}, {y} \n Δ={deviation:.2f} Meter)",
                    (x, y),
                    textcoords="offset points",
                    xytext=(80, 5),  
                    fontsize=8)
        total_deviation += abs(deviation)
    avg_deviation = total_deviation / len(dist_comms)
    ax1.plot(dist_comms_mod_shannon_strict, data_rates, label=f"Modified shannon MM8108 with avg deviation of {avg_deviation:.2f} Meter Strict")
    # FOR EXP PLOT
    # # for regression curve order size 4 is used as highest without significiantly seing overfit
    # params, _ = curve_fit(exp_model,dist_comms,data_rates, p0=(max(data_rates), 0.001))   # initial guess)
    # scale_exp, exp_param = params
    # # for plotting regression
    # x_line = np.linspace(min(dist_comms), 30000, 200)
    # y_line = exp_model(x_line, scale_exp, exp_param)
    # total_deviation_reg = 0
    # for x, y in zip(dist_comms, data_rates):
    #     predicted_rate = exp_model(x,scale_exp, exp_param)
    #     deviation = y - predicted_rate            # residual
    #     ax1.annotate(f"({x:.2f}, {y} \n Δ={deviation:.2f} Mbps)",
    #                 (x, y),
    #                 textcoords="offset points",
    #                 xytext=(5, 5),  
    #                 fontsize=8)
    #     total_deviation_reg += abs(deviation)
    # avg_deviation_reg = total_deviation_reg / len(dist_comms)
    # ax1.plot(x_line, y_line, label=f"Regression curve with avg deviation of {avg_deviation_reg:.2f} Mbps")
    ax1.legend()
    plt.show()

def process_drone_mesh(*,
                       
                       grid_prefix: str,
                       wireless_prefix:str,
                       dist_comm: float,
                       dim: tuple[float, float],
                       sample_resolution: tuple[float, float],
                       tolerances: np.ndarray,
                       drone_distance_redundancy: float,
                       dropout_rates: np.ndarray,
                       dropout_iters: int,
                       hist_plot: bool,
                       margin_loss_db: float,
                       eta: float = 0.79,
                       snr_eff: float = 0.14,
                       grid_func,
                       **kwargs):
    """
    Docstring for process_drone_mesh

    Inputs:
    grid_prefix: Name for plot title, file name and folder for given grid type
    dist_comm: Communication distance of drone in meters
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    sample_resolution: Sample resolution [x, y] ie. how many sample points inside the dimensions
    tolerances: Tx1 numpy array of distance tolerances used for calculating distance between drones
    drone_distance_redundancy: Distance redundancy used in calc_distance function for placing drones in grid
    dropout_rates: Nx1 numpy array of percentages of drones which are removed (0..1)
    dropout_iters: Number of iterations for each dropout rate (used for histogram)
    grid_func: Grid functions which outputs numpy array of drone positions in given grid type
    grid_func_kwargs: Input dimentions only, distance is calculated in this function

    Returns:
    Saves drone position plots for both full drone mesh and one partial drone mesh(after dropout) in .png file
    Saves histogram of drone link count for both full drone mesh and total link count for (dropout_iters) partial drone meshes fro each tolerance in .png file
    Saves drone network graph of full drone mesh and one example of a partial drone mesh after dropout in a .json file
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
    dir_origin_full_plots = os.path.join(dir_origin, "full/plots/")
    dir_origin_full_json = os.path.join(dir_origin, "full/json/")
    dir_origin_partial_plots = os.path.join(dir_origin, "partial/plots/")
    dir_origin_partial_json = os.path.join(dir_origin, "partial/json/")

    # Chech if output is valid else make it
    os.makedirs(dir_origin, exist_ok=True)
    os.makedirs(dir_origin_full_plots, exist_ok=True)
    os.makedirs(dir_origin_full_json, exist_ok=True)
    os.makedirs(dir_origin_partial_plots, exist_ok=True)
    os.makedirs(dir_origin_partial_json, exist_ok=True)

    # For loop over number of tolerances
    for i in range(len(tolerances)):

        tolerance = tolerances[i]
        # Calculate distance from wireless communication range and tolerances
        drone_distance = distance_calc(dist_comm, tolerance, drone_distance_redundancy)

        # Choose grid function
        all_drone_positions = grid_func(dim=dim, dist=drone_distance, **kwargs)

        # For loop over number of dropouts
        bar_dropout_rates = tqdm(dropout_rates)
        for j, dropout_rate in enumerate(bar_dropout_rates):
            bar_dropout_rates.set_description(f"Processing {grid_prefix} mesh tol={tolerance} | all rates {dropout_rates} | current dropout={dropout_rate:.2f}")

            # Iterate over dropout rates and add to metadata
            #dropout_rate = dropout_rates[j]
            metadata[f"{grid_prefix}_{j}_DROPOUT_RATE"] = dropout_rate

            # Create array for total number of link count for dropout networks
            total_link_count_dropout = []

            # Create variable for network is fully connected percentage
            connected_count = 0

            # For loop over dropout iterations for histogram
            for _ in range(dropout_iters):
                drone_positions_dropout = dropout_drones(meta_prefix=f"{grid_prefix}_{j}_", drone_positions=all_drone_positions, dropout_rate=dropout_rate)
                
                # Make node and link list for partial drone mesh with removed drones
                node_list_dropout = node_list(drone_positions=drone_positions_dropout)
                link_list_dropout, link_count_dropout = link_list(wireless_prefix=wireless_prefix, 
                                                                  nodes=node_list_dropout, 
                                                                  dist_comm=dist_comm,
                                                                  margin_loss_db= margin_loss_db,
                                                                  eta=eta,
                                                                  snr_eff=snr_eff)

                # Make array of all link counts for partial drone mesh 
                total_link_count_dropout.append(link_count_dropout)

                # Check if the remaining network after dropout is fully connected
                if is_network_fully_connected(node_list_dropout, link_list_dropout):
                    connected_count += 1
                
                # Calculate the connected percentage of given dropout mesh
                metadata[f"{grid_prefix}_{j}_CONNECTED_PERCENTAGE"] = connected_count / dropout_iters

            # Metaprefix for file names
            prefix_dropout_real_perc = metadata[f"{grid_prefix}_{j}_DROPOUT_REAL_PERCENTAGE"]

            # Make single network of each dropout rate
            make_json_network(file_name=f"{grid_prefix}_network_{prefix_dropout_real_perc}_dropout_{tolerance}_tolerance.json", 
                              file_folder_path=dir_origin_partial_json, 
                              nodes=node_list_dropout, 
                              links=link_list_dropout)

            # Calculating links from devices to drones for partial drone mesh
            calculate_device_links(meta_prefix= f"{grid_prefix}_{j}_DROPOUT_", 
                                   nodes=node_list_dropout, 
                                   dim=dim, 
                                   dist_comm=dist_comm, 
                                   sample_resolution=sample_resolution)
        
            # Histogram and drone position plots over total iterations
            if hist_plot == True:
                plot_histogram_drone_links(file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.4f}_dropout_{tolerance}_tolerance_histogram.png",
                                            title_name=f"{grid_prefix} Histogram | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                                            drone_link_count=total_link_count_dropout,
                                            iterations=dropout_iters,
                                            file_folder_path=dir_origin_partial_plots)
            
            plot_drone_positions(meta_prefix=f"{grid_prefix}_{j}_DROPOUT_",
                                 file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.4f}_dropout_{tolerance}_tolerance_mesh.png",
                                 title_name=f"{grid_prefix} Mesh | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                                 nodes=node_list_dropout,
                                 distance=drone_distance,
                                 dist_comm=dist_comm,
                                 drone_link_count=link_count_dropout,
                                 file_folder_path=dir_origin_partial_plots)

        # Make node and link list for full drone mesh
        node_list_all = node_list(drone_positions=all_drone_positions)
        link_list_all, link_count_all = link_list(wireless_prefix=wireless_prefix,
                                                  nodes=node_list_all, 
                                                  dist_comm=dist_comm,
                                                  margin_loss_db= margin_loss_db,
                                                  eta=eta,
                                                  snr_eff=snr_eff)

        # Add number drones used in full mesh to metadata
        metadata[f"{grid_prefix}_ALL_NUMBER_DRONES"] = len(node_list_all)

        # Make the json network from list of nodes
        make_json_network(file_name=f"{grid_prefix}_network.json", 
                          file_folder_path=dir_origin_full_json, 
                          nodes=node_list_all, 
                          links=link_list_all)

        # Calculating links from devices to drones for full drone mesh
        calculate_device_links(meta_prefix=f"{grid_prefix}_ALL_", 
                               nodes=node_list_all, 
                               dim=dim, 
                               dist_comm=dist_comm,
                               sample_resolution=sample_resolution)


        # Histogram and drone position plots over full drone mesh
        if hist_plot == True:
            plot_histogram_drone_links(file_name=f"{grid_prefix}_{tolerance}_tolerance_full_histogram.png",
                                    title_name=f"{grid_prefix} Histogram | tolerance = {tolerance} [m]",
                                    drone_link_count=link_count_all,
                                    file_folder_path=dir_origin_full_plots)
            
        plot_drone_positions(meta_prefix=f"{grid_prefix}_ALL_",
                             file_name=f"{grid_prefix}_{tolerance}_tolerance_full_mesh.png",
                             title_name=f"{grid_prefix} Mesh | tolerance = {tolerance} [m]",
                             nodes=node_list_all,
                             distance=drone_distance,
                             dist_comm=dist_comm,
                             drone_link_count=link_count_all,
                             file_folder_path=dir_origin_full_plots)

    with open(os.path.join(dir_origin, "metadata.json"), "w") as f:
        json.dump(metadata, f)

def main():
    ###############################################################################
    #__________________________ TEST PARAMETERS __________________________________#
    ###############################################################################
    # dimensions of area
    length = 30000
    width = 10000
    scale_factor = 1
    test_dim = (length*scale_factor, width*scale_factor)
    test_samples = (600, 200)                           # number of sample points on area (x, y)

    test_tolerances = np.arange(100, 300, 100)          #tolerance in meters (min, max, stepsize) 
    test_dist_redundancy = 0                            # distance redundancy for drone placement
    test_dropout_rates = np.arange(0.1, 0.3, 0.1)       #dropout rate in percentage (min, max, stepsize)
    test_dropout_iters = 100                            # number of iterations for each dropout rate (used for histogram)
    
    # wireless communication parameters for MM8108-MF15457 lookup table
    wireless_prefix = ""
    desired_bandwidth_Mhz = 8
    desired_rate_Mbps = 20
    freq_Mhz = 868
    margin_loss_db = 3                                  # safety variable for "other" losses

    # Set grid type to process
    # if hexagonal grid is chosen bool variable extra_edge_drones 
    # has to be set in function process_drone_mesh
    test_grid_meta_prefix = "Square"
    test_grid_func = drone_sq_grid
    graph_plots = False
    eta = 0.79
    snr_eff = 0.14
    ###############################################################################
    ###############################################################################

    # Save test parameters to metadata
    metadata["AREA_DIMENSIONS"] = str(test_dim)
    metadata["SAMPLES"] = str(test_samples)
    metadata["TOLERANCES"] = str(test_tolerances)
    metadata["DROPOUT_RATES"] = str(test_dropout_rates)
    metadata["DISTANCE_REDUNDANCY"] = test_dist_redundancy

    metadata["FREQ_MHZ"] = freq_Mhz
    metadata["MARGIN_LOSS"] = margin_loss_db

    # Save dropout iterations used for histogram
    metadata["DROPOUT_ITERATIONS"] = test_dropout_iters

    # Calculate values for modelling wireless commmunication from wifi halow module
    # These values are the same for all grid types
    get_halow_module_MM8108_params(wireless_prefix=wireless_prefix, 
                                   desired_bandwidth_Mhz=desired_bandwidth_Mhz, 
                                   desired_rate_Mbps=desired_rate_Mbps)

    if graph_plots == True:
        graph_sensitivity_phyrate(desired_bandwidth_Mhz=desired_bandwidth_Mhz,eta_strict=eta,snr_eff_strict=snr_eff)
        graph_range_phyrate(desired_bandwidth_Mhz=desired_bandwidth_Mhz,eta_strict=eta,snr_eff_strict=snr_eff)

    # for checking given a distance what do i get as the datarate
    # data_rate_mbps = data_rate_given_dist_comm(distance_m=30000,
    #                                            bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
    #                                            transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
    #                                            margin_loss_db=margin_loss_db)
    # print(f"{data_rate_mbps=}")

    dist_comm = dist_comm_calc(transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"], 
                               received_power_dbm=metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"], 
                               freq_Mhz=freq_Mhz,
                               margin_loss_db=margin_loss_db)
    
    # Process a drone mesh to give metadata and plots
    process_drone_mesh(grid_prefix=test_grid_meta_prefix,
                       wireless_prefix=wireless_prefix,
                       dist_comm=dist_comm,
                       dim=test_dim,
                       sample_resolution=test_samples,
                       tolerances=test_tolerances,
                       drone_distance_redundancy=test_dist_redundancy,
                       dropout_rates=test_dropout_rates,
                       dropout_iters=test_dropout_iters,
                       hist_plot= True,
                       margin_loss_db=margin_loss_db,
                       eta=eta,
                       snr_eff=snr_eff,
                       grid_func=test_grid_func,
                    )
    
if __name__ == "__main__":
    main()

