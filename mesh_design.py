import numpy as np
import matplotlib.pyplot as plt
import math
import os
from tqdm import tqdm
from collections import Counter
import json
from dataclasses import dataclass, asdict

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
    
###############################################################################
#__________________________ DRONE MESH GRIDS _________________________________#
###############################################################################
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

def distance_calc(dist_comm: float, 
                  tolerance: float, 
                  dist_redundancy: float) -> float:

    distance = dist_comm - tolerance - dist_redundancy

    return distance
    
# Shannon for calculating received power (not in use due to reuslt 48 km :)
def shannon(data_rate_Mbps: float, 
            bandwidth_Mhz: float = 4, 
            noise_figure_db: float = 6) -> float:
    """
    default values:

    bandwidth = 5 MHz (bandwidth of wifi halow)
    noise_figure = 3db (double of ideal thermal noise) usually 3-5db
    transmit_power_dbm = 24dbm
    transmit_gain_dbi = 0 (isotropic) usually in range 0-3 dbi
    received_gain_dbi = 0 usually in range 0-3 dbi
    margin_loss_db = 2 dB (other losses like polarization mismatch)
    freq_mhz = 863 - 868 (wifi halow)
    """


    # Calculate shannon 
    # data_rate_bps = bandwidth_hz * math.log2(1 + (signal_power/noise_power))
    # isolate snr
    data_rate_bps = data_rate_Mbps * 10**6 # convert datarate from Mpbs to bps
    bandwidth_hz = bandwidth_Mhz * 10**6 # convert bandwidth from Mhz to Hz
    snr = 2**(data_rate_bps/bandwidth_hz) - 1
    snr_db = 10* math.log10(snr)

    # Calculate noise power (-174 dbm/Hz is thermal noise density )
    noise_power_dbm = -174 + 10 * math.log10(bandwidth_hz) + noise_figure_db

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
                                   meta_prefix: str ="",
                                   desired_bandwidth_Mhz, 
                                   desired_rate_Mbps):
    # Find closest available bandwidth
    available_bandwidth = np.array(list(lookup_table_halow_module_MM8108.keys()))
    bandwidth_index = np.argmin(np.abs(available_bandwidth - desired_bandwidth_Mhz))
    closest_bandwidth = int(available_bandwidth[bandwidth_index])
    metadata[f"{meta_prefix}BANDWIDTH"] = closest_bandwidth

    # Get all MCS schemes for that bandwidth
    schemes = lookup_table_halow_module_MM8108[closest_bandwidth].values()

    # Find the sorted_scheme with data_rate closest to desired_rate_Mbps
    sorted_schemes = sorted(schemes, key=lambda s: abs(s['data_rate'] - desired_rate_Mbps))

    # Find first sorted_scheme >= desired datarate
    for best_scheme in sorted_schemes:
        if best_scheme['data_rate'] >= desired_rate_Mbps:
            metadata[f"{meta_prefix}DATA_RATE"] = best_scheme['data_rate']
            metadata[f"{meta_prefix}RECEIVED_SENSITIVITY"] = best_scheme['receive_sensitivity']
            metadata[f"{meta_prefix}TRANSMIT_POWER"] = best_scheme['transmit_power']
            break
        else:
            # If desired data rate above all availeble schemes return highest sorted_scheme
            best_scheme = sorted_schemes[0]
            metadata[f"{meta_prefix}DATA_RATE"] = best_scheme['data_rate']
            metadata[f"{meta_prefix}RECEIVED_SENSITIVITY"] = best_scheme['receive_sensitivity']
            metadata[f"{meta_prefix}TRANSMIT_POWER"] = best_scheme['transmit_power']

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
                           tqdm_grid_title: str,
                           drone_positions: np.ndarray,
                           dim: tuple[float, float],
                           dist_comm: float,
                           sample_resolution: tuple[float, float]) -> np.ndarray:
    """
    Docstring for calculate_device_links
    
    Inputs:
    grid_name: Name of grid used for file and plot name
    drone_positions: Nx2 Numpy array of drone positions in a given mesh
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    sample_resolution: Sample resolution [x, y] ie. how many sample points inside the dimensions
    
    Returns: Dx1 numpy array of drone links for each device
    """

    x_dim, y_dim = dim
    x_sample_res, y_sample_res = sample_resolution
    # Device points in drone area
    x_device_points = np.linspace(0, x_dim, x_sample_res)
    y_device_points = np.linspace(0, y_dim, y_sample_res)

    valid_links_counts = []

    for x_new in tqdm(x_device_points, desc=f"Computing distances for {tqdm_grid_title} mesh"):
        for y_new in y_device_points:
            # Compute distances from device i to all drones
            distances = (drone_positions[:, 0] - x_new)**2 + (drone_positions[:, 1] - y_new)**2

            # Add links to valid connection count
            links = np.sum(distances <= dist_comm**2)

            valid_links_counts.append(links)
    
    valid_links = np.array(valid_links_counts)

    # Saving min and mean in dict for drone plot
    metadata[f"{meta_prefix}MIN_DEVICE_LINKS"] = float(np.min(valid_links))
    metadata[f"{meta_prefix}MEAN_DEVICE_LINKS"] = float(np.mean(valid_links))


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

def link_list(nodes: list,
              dist_comm: float) -> list[Link]:
    
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

            if distances <= (dist_comm + 1)**2:
                link = Link(source=source.id, target=target.id)
                links.append(link)       
        
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

# TODO make so drone positions takes node list instead of numpy array
def plot_drone_positions(*,
                         meta_prefix: str = "", 
                         grid_name: str,
                         drone_positions: np.ndarray,
                         distance: float,
                         dist_comm: float,
                         drone_link_count: np.ndarray,
                         file_folder_path: str,
                         font_size: float = 8.0):
    
    fig, ax_drone_pos = plt.subplots()
    
    # Plot drone positions as dots
    x_pos = drone_positions[:, 0]
    y_pos = drone_positions[:, 1]
    ax_drone_pos.plot(x_pos, y_pos, 'o', color = 'red', markersize=2)


    for i, (x, y) in enumerate(drone_positions):
        # Draw communcation dist_comm as circle
        circle = plt.Circle((x, y), dist_comm, fill=True, facecolor='blue', edgecolor='black', alpha=0.1)
        ax_drone_pos.add_patch(circle)

    device_links_min = metadata[f"{meta_prefix}MIN_DEVICE_LINKS"]
    device_links_mean = metadata[f"{meta_prefix}MEAN_DEVICE_LINKS"]

    title_text = (
    f"{grid_name} Mesh, Drones = {len(drone_positions)}, d = {distance:.2f} [m], dist_comm = {dist_comm:.2f} [m] \n"
    f"Drone links: Min = {np.min(drone_link_count)}, Avg = {np.mean(drone_link_count):.2f} \n "
    f"Device links: Min = {device_links_min}, Avg = {device_links_mean:.2f}"
)
    ax_drone_pos.set_title(title_text, fontsize=font_size, pad=10)  # pad adds space above plot
    ax_drone_pos.set_xlabel("meters", fontsize=font_size)
    ax_drone_pos.set_ylabel("meters", fontsize=font_size)
    ax_drone_pos.set_aspect('equal', 'box')
    ax_drone_pos.tick_params(axis='both', labelsize=font_size)

    file_path = os.path.join(file_folder_path, f"{grid_name}.png")
    fig.savefig(file_path, dpi=300, bbox_inches='tight')
    
    plt.close(fig)

def plot_histogram_drone_links(file_name: str,
                               drone_link_count: np.ndarray,
                               file_folder_path: str,
                               font_size: float = 8.0):

    # Build histogram of # drones and # links
    fig_hist, ax_hist = plt.subplots()

    # Flatten if input is list of lists
    if any(isinstance(i, list) for i in drone_link_count):
        drone_link_count = [count for sublist in drone_link_count for count in sublist]

    connections_hist = Counter(drone_link_count)
    ax_hist.set_title("Histogram over links")
    ax_hist.set_xlabel("Connections", fontsize=font_size)
    ax_hist.set_ylabel("Drones", fontsize=font_size)
    ax_hist.bar(connections_hist.keys(), connections_hist.values(), width=0.2)

    file_path_hist = os.path.join(file_folder_path, file_name)
    fig_hist.savefig(file_path_hist, dpi=300, bbox_inches='tight')
    plt.close(fig_hist)





def main():
    """
    Docstring for main
    
    Inputs:
    grid_name: Name of grid used for file and plot name
    all_drone_positions: Nx2 Numpy array of all drone positions in a given mesh
    distance: Distance between drones in meters
    dist_comm: Communication distance of drone in meters
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    sample_resolution: Sample resolution [x, y] ie. how many sample points inside the dimensions
    file_folder_path: File path to folder where plots will be saved
    dropout_rate: Percetage of drones which are removed (0..1)

    This function takes a given drone mesh and 
    - plots the mesh of drones of all drones and one example of drones with dropout
    - plots histogram of number drones against links to other drones

    """
    ###############################################################################
    #__________________________ TEST PARAMETERS __________________________________#
    ###############################################################################
    length = 30000
    width = 10000
    scale_factor = 1

    test_dim = (length*scale_factor, width*scale_factor)
    samples = (600, 200)
    file_folder_path = "./mesh_design_out" 

    test_tolerances = np.arange(100, 300, 100)  #tolerance in meters (min, max, stepsize) 
    test_dist_redundancy = 0
    dropout_rates = np.arange(0.1, 0.3, 0.1)    #dropout rate in percentage (min, max, stepsize)
    dropout_iters = 100                         # number of iterations for each dropout rate (used for histogram)

    wireless_prefix = ""
    desired_bandwidth_Mhz = 8
    desired_rate_Mbps = 20
    freq_Mhz = 868
    margin_loss_db = 3
    ###############################################################################
    ###############################################################################

    # Chech if output is valid else make it
    os.makedirs(file_folder_path, exist_ok=True)

    # Save dropout iterations used for histogram
    metadata["DROPOUT_ITERATIONS"] = dropout_iters


    # Calculate values for modelling wireless commmunication from wifi halow module
    # These values are the same for all grid types
    get_halow_module_MM8108_params(meta_prefix=wireless_prefix, 
                                   desired_bandwidth_Mhz=desired_bandwidth_Mhz, 
                                   desired_rate_Mbps=desired_rate_Mbps)

    dist_comm = dist_comm_calc(transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"], 
                               received_power_dbm=metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"], 
                               freq_Mhz=freq_Mhz,
                               margin_loss_db=margin_loss_db)
 
    # For loop over number of tolerances
    for i in range(len(test_tolerances)):

        tolerance = test_tolerances[i]
        # Calculate distance from wireless communication range and tolerances
        drone_distance = distance_calc(dist_comm, tolerance, test_dist_redundancy)

        # Choose grid function
        all_drone_positions = drone_sq_grid(dim=test_dim, dist=drone_distance)

        # For loop over number of dropouts
        for j in range(len(dropout_rates)):
            dropout_rate = dropout_rates[j]
            
            total_link_count_dropout = []

            # For loop over dropout iterations for histogram
            for k in range(dropout_iters):
                drone_positions_dropout = dropout_drones(meta_prefix=f"SQUARE_{j}_", drone_positions=all_drone_positions, dropout_rate=dropout_rate)
                
                # Make node and link list for partial drone mesh with removed drones
                node_list_dropout = node_list(drone_positions=drone_positions_dropout)
                link_list_dropout, link_count_dropout = link_list(nodes=node_list_dropout, dist_comm=dist_comm)

                # Make array of all link counts for partial drone mesh 
                total_link_count_dropout.append(link_count_dropout)
            
            
            # Make single network of each dropout rate
            make_json_network(file_name="square_network_dropout_example.json", 
                              file_folder_path=file_folder_path, 
                              nodes=node_list_dropout, 
                              links=link_list_dropout)

            # Calculating links from devices to drones for partial drone mesh
            calc_dev_links_partial = metadata[f"SQUARE_{j}_DROPOUT_REAL_PERCENTAGE"]
            calculate_device_links(meta_prefix= f"SQUARE_{j}_DROPOUT", 
                                   tqdm_grid_title=f"SQUARE_LINKS_{calc_dev_links_partial}", 
                                   drone_positions=drone_positions_dropout, 
                                   dim=test_dim, 
                                   dist_comm=dist_comm, 
                                   sample_resolution=samples)

            # Histogram and drone position plots over total iterations (not mean)
            plot_histogram_drone_links(file_name=f"SQUARE_LINKS_{calc_dev_links_partial}_hist.png",
                                       drone_link_count=total_link_count_dropout,
                                       file_folder_path=file_folder_path)
            
            plot_drone_positions(meta_prefix=f"SQUARE_{j}_DROPOUT",
                                 grid_name=f"SQUARE_LINKS_{calc_dev_links_partial}",
                                 drone_positions=drone_positions_dropout,
                                 distance=drone_distance,
                                 dist_comm=dist_comm,
                                 drone_link_count=link_count_dropout,
                                 file_folder_path=file_folder_path)

        # Make node and link list for full drone mesh
        node_list_all = node_list(drone_positions=all_drone_positions)
        link_list_all, link_count_all = link_list(nodes=node_list_all, dist_comm=dist_comm)

        # Make the json network from list of nodes
        make_json_network(file_name="square_network.json", file_folder_path=file_folder_path, nodes=node_list_all, links=link_list_all)

        # Calculating links from devices to drones for full drone mesh
        calculate_device_links(meta_prefix="square_all", 
                               tqdm_grid_title="square_all", 
                               drone_positions=all_drone_positions, 
                               dim=test_dim, 
                               dist_comm=dist_comm,
                               sample_resolution=samples)


        # Histogram and drone position plots over full drone mesh
        plot_histogram_drone_links(file_name="square_full_mesh.png",
                                   drone_link_count=link_count_all,
                                   file_folder_path=file_folder_path)
            
        plot_drone_positions(meta_prefix="square_all",
                             grid_name="square_all",
                             drone_positions=all_drone_positions,
                             distance=drone_distance,
                             dist_comm=dist_comm,
                             drone_link_count=link_count_all,
                             file_folder_path=file_folder_path)

    with open(os.path.join(file_folder_path, "metadata.json"), "w") as f:
        json.dump(metadata, f)

if __name__ == "__main__":
    main()

