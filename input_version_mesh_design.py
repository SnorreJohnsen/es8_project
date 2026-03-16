import numpy as np
import matplotlib.pyplot as plt
import math
import os
import pandas as pd
from tqdm import tqdm
from collections import Counter
from statistics import mean
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

def make_device_grid(dim: tuple[float, float],
                     z_height: float,
                     sample_resolution: tuple[float, float]):

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
    grid_name: Name of grid used for file and plot name
    nodes: List of nodes contataining of drone positions in a given mesh
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    sample_resolution: Sample resolution [x, y] ie. how many sample points inside the dimensions

    Returns:
    Saves min and max device links to metadata
    Saves percentage of area covered to metadata
    """

    # Extract drone position from list -> shape (N_points, 2)
    drone_positions = np.asarray([[node.x, node.y, node.z] for node in nodes])

    # Compute squared distances using broadcasting
    # device_points[:, None, :] -> (N_points, 1, 3)
    # drone_positions[None, :, :] -> (1, N_drones, 3)
    # Result -> (N_points, N_drones)
    diff = device_positions[:, None, :] - drone_positions[None, :, :]
    distances_sq = np.sum(diff**2, axis=2)                                  # euclidean distance
    min_dist_sq_per_device = np.min(distances_sq, axis=1)                   # find shortest distance for each device
    min_dist_per_device= np.sqrt(min_dist_sq_per_device)
    



    # This need to be removed here after 

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

    return min_dist_per_device

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
              use_lookup_table: bool = False) -> list[Link]:

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
            distances = (target.x - source.x)**2 + (target.y - source.y)**2 + (target.z - source.z)**2
               
            if use_lookup_table == False:

                # if distances <= (dist_comm + 1)**2:
                #predicted_rate= exp_model(np.sqrt(distances), scale_exp, exp_param)
                data_rate_mbps = data_rate_given_dist_comm(distance_m=np.sqrt(distances),
                                                bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                                                transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                                                margin_loss_db=margin_loss_db,
                                                eta=eta,
                                                snr_eff=snr_eff,
                                                freq_Mhz=metadata["FREQ_MHZ"])
            else:
                rate_ranges = []

                for key, value in metadata.items():
                    if key.lower().endswith("_mbps_range"):
                        rate = float(key.split("_")[0])
                        rate_ranges.append((rate, value))

                rate_ranges.sort(key=lambda x: x[1],reverse=True)  # sort by range

                data_rate_mbps = 0
                # find correct rate
                for rate, rng in rate_ranges:
                    if distances <= rng**2:
                        data_rate_mbps = rate

            link = Link(source=source.id,
                            target=target.id,
                            bandwidth_mbit=f"{data_rate_mbps:.2f}")
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
                         wireless_prefix: str = "",
                         title_name: str,
                         file_name: str,
                         nodes: list,
                         device_positions: np.ndarray,
                         distance: float,
                         dist_comm: float,
                         dist_device_to_drone: np.ndarray,
                         links: list,
                         eta: float,
                         snr_eff: float,
                         file_folder_path: str,
                         font_size: float = 8.0):

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
    

    rates_for_devices= np.array([ data_rate_given_dist_comm(s,
                              bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
                              transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
                              margin_loss_db=metadata["MARGIN_LOSS"],
                              eta=eta,
                              snr_eff=snr_eff,
                              freq_Mhz=metadata["FREQ_MHZ"]
                              ) for s in dist_device_to_drone ])
    
    phyrates = [float(link.bandwidth_mbit) for link in links]
    
    # print(dist_device_to_drone)
    #print(rates_for_devices)

    for _, node in enumerate(nodes):
        x = node.x
        y = node.y

        # Draw communcation dist_comm as circle
        circle = plt.Circle((x, y), dist_comm, fill=True, facecolor='blue', edgecolor='black', alpha=0.1)
        ax_drone_pos.add_patch(circle)

    if len(x_device_pos) == 1:
        title_text = (
        f"{title_name}\n"
        f"Drones = {len(nodes)}, d = {distance:.2f} [m], dist_comm = {dist_comm:.2f} [m] \n"
        f" Device PHYrate: Min = {np.min(rates_for_devices):.2f}, Avg = {np.mean(rates_for_devices):.2f} \n"
        f"Drone PHYrate [Mbps]: Min = {min(phyrates):.2f}, Avg = {mean(phyrates):.2f}, Max = {max(phyrates):.2f}"
        )
    else:
        title_text = (
        f"{title_name}\n"
        f"Drones = {len(nodes)}, d = {distance:.2f} [m], dist_comm = {dist_comm:.2f} [m] \n"
        f"Drone PHYrate [Mbps]: Min = {min(phyrates):.2f}, Avg = {mean(phyrates):.2f}, Max = {max(phyrates):.2f}"
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
    available_bandwidth = np.array(list(lookup_table.keys()))
    bandwidth_index = np.argmin(np.abs(available_bandwidth - desired_bandwidth_Mhz))
    closest_bandwidth = int(available_bandwidth[bandwidth_index])

    # Get all MCS schemes for that bandwidth
    schemes = lookup_table[closest_bandwidth].values()

    # Find the sorted_scheme with data_rate closest to desired_rate_Mbps
    sorted_schemes = sorted(schemes, key=lambda s: s['data_rate'])

    return sorted_schemes, closest_bandwidth

def graph_sensitivity_phyrate(metadata: dict,
                              file_folder_path: str,
                              filename: str,
                              desired_bandwidth_Mhz: float,
                              lookup_table:dict,
                              lookup_table_name: str,
                              enable_plot: bool
                              ):
    os.makedirs(file_folder_path,exist_ok=True)

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
        file_path_graph = os.path.join(file_folder_path,filename)
        fig.savefig(file_path_graph,dpi=300,bbox_inches='tight')
        plt.close(fig)

def graph_range_phyrate(metadata: dict,
                        file_folder_path: str,
                        filename: str,
                        desired_bandwidth_Mhz: float,
                        lookup_table: dict,
                        lookup_table_name: str,
                        enable_plot: bool,
                        save_ranges: bool = True
                        ):
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
        if save_ranges == True:
            metadata[f"{y:.2f}_Mbps_range"] = z_strict

    # averages
    avg_deviation_opt = total_deviation_opt / len(dist_comms)
    avg_deviation_strict = total_deviation_strict / len(dist_comms)

    # create table
    df = pd.DataFrame(rows)

    df.to_latex(f"{file_folder_path}_table_bandwidth_{desired_bandwidth_Mhz}_MHz.tex", index=False)

    # FIGURE
    if enable_plot == True:
        fig, ax1 = plt.subplots(figsize=(16, 9))
        plt.xscale('log')  # set x-axis to logarithmic
        ax1.set_xlabel("Range (m)", fontsize=18)
        ax1.set_ylabel("PHY Rate (Mbps)", fontsize=18)
        ax1.tick_params(axis='both', which='major', labelsize=16)
        ax1.plot(dist_comms, data_rates,'x',color = "orange")
        ax1.step(dist_comms, data_rates, where='post', label=f"Datasheet {lookup_table_name}", color = "orange")
        ax1.plot(dist_comms_mod_shannon_optimal, data_rates, color="green", label=f"Modified shannon {lookup_table_name} with avg deviation of {avg_deviation_opt:.2f} (m) optimal")
        ax1.plot(dist_comms_mod_shannon_strict, data_rates, color="red", label=f"Modified shannon {lookup_table_name} with avg deviation of {avg_deviation_strict:.2f} (m) strict")

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
        ax1.legend(fontsize=18, loc='upper right')
        file_path_graph = os.path.join(file_folder_path,filename)
        fig.savefig(file_path_graph,dpi=300, bbox_inches = 'tight')
        plt.close(fig)

def process_drone_mesh(*,
                       grid_prefix: str,
                       wireless_prefix:str,
                       dist_comm: float,
                       dim: tuple[float, float],
                       drone_height: float,
                       tolerances: np.ndarray,
                       drone_distance_redundancy: float,
                       dropout_rates: np.ndarray,
                       dropout_iters: int,
                       hist_plot: bool,
                       margin_loss_db: float,
                       device_grid: np.ndarray,
                       link_budget_model: bool,
                       grid_func,
                       **kwargs):
    """
    Docstring for process_drone_mesh

    Inputs:
    grid_prefix: Name for plot title, file name and folder for given grid type
    dist_comm: Communication distance of drone in meters
    dim: Dimensions [x, y] of the area the drone mesh need to cover
    height: Drone height [z]
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

    data_rate_Mbps = metadata[f"{wireless_prefix}DATA_RATE"] 
    bandwidth_Mhz = metadata[f"{wireless_prefix}BANDWIDTH"]

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
                                                                  eta=metadata["ETA_STRICT"],
                                                                  snr_eff=metadata["SNR_EFF_STRICT"],
                                                                  use_lookup_table=link_budget_model)

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
            make_json_network(file_name=f"{grid_prefix}_network_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz.json",
                              file_folder_path=dir_origin_partial_json,
                              nodes=node_list_dropout,
                              links=link_list_dropout)

            # Calculating links from devices to drones for partial drone mesh
            dist_device_to_drone= calculate_device_links(meta_prefix= f"{grid_prefix}_{j}_DROPOUT_",
                                   nodes=node_list_dropout,
                                   dist_comm=dist_comm,
                                   device_positions=device_grid)

            # Histogram and drone position plots over total iterations
            if hist_plot == True:
                plot_histogram_drone_links(file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_histogram.png",
                                            title_name=f"{grid_prefix} Histogram | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                                            drone_link_count=total_link_count_dropout,
                                            iterations=dropout_iters,
                                            file_folder_path=dir_origin_partial_plots)

            plot_drone_positions(meta_prefix=f"{grid_prefix}_{j}_DROPOUT_",
                                 wireless_prefix = wireless_prefix,
                                 file_name=f"{grid_prefix}_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_mesh.png",
                                 title_name=f"{grid_prefix} Mesh | dropout = {prefix_dropout_real_perc*100:.2f}% tolerance = {tolerance} [m]",
                                 nodes=node_list_dropout,
                                 device_positions=device_grid,
                                 distance=drone_distance,
                                 dist_comm=dist_comm,
                                 dist_device_to_drone=dist_device_to_drone,
                                 links=link_list_dropout,
                                 eta=metadata["ETA_STRICT"],
                                 snr_eff=metadata["SNR_EFF_STRICT"],
                                 file_folder_path=dir_origin_partial_plots)

        # Make node and link list for full drone mesh
        node_list_all = node_list(drone_positions=all_drone_positions)
        link_list_all, link_count_all = link_list(wireless_prefix=wireless_prefix,
                                                  nodes=node_list_all,
                                                  dist_comm=dist_comm,
                                                  margin_loss_db= margin_loss_db,
                                                  eta=metadata["ETA_STRICT"],
                                                  snr_eff=metadata["SNR_EFF_STRICT"],
                                                  use_lookup_table=link_budget_model)

        # Add number drones used in full mesh to metadata
        metadata[f"{grid_prefix}_ALL_NUMBER_DRONES"] = len(node_list_all)

        # Make the json network from list of nodes
        make_json_network(file_name=f"{grid_prefix}_network_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz.json",
                          file_folder_path=dir_origin_full_json,
                          nodes=node_list_all,
                          links=link_list_all)

        # Calculating links from devices to drones for full drone mesh
        calculate_device_links(meta_prefix=f"{grid_prefix}_ALL_",
                               nodes=node_list_all,
                               dist_comm=dist_comm,
                               device_positions=device_grid)

        # Histogram and drone position plots over full drone mesh
        if hist_plot == True:
            plot_histogram_drone_links(file_name=f"{grid_prefix}_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_histogram.png",
                                    title_name=f"{grid_prefix} Histogram | tolerance = {tolerance} [m]",
                                    drone_link_count=link_count_all,
                                    file_folder_path=dir_origin_full_plots)

        plot_drone_positions(meta_prefix=f"{grid_prefix}_ALL_",
                             wireless_prefix=wireless_prefix,
                             file_name=f"{grid_prefix}_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_mesh.png",
                             title_name=f"{grid_prefix} Mesh | tolerance = {tolerance} [m]",
                             nodes=node_list_all,
                             device_positions=device_grid,
                             distance=drone_distance,
                             dist_comm=dist_comm,
                             dist_device_to_drone=dist_device_to_drone,
                             links=link_list_all,
                             eta=metadata["ETA_STRICT"],
                             snr_eff=metadata["SNR_EFF_STRICT"],
                             file_folder_path=dir_origin_full_plots)

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

    available_bandwidth = list(lookup_table.keys())
    print(f"Bandwidth possibilities {available_bandwidth}")
    metadata["FREQ_MHZ"] = freq_Mhz



    desired_bandwidth_Mhz = int(input("Bandwidth: "))
    print()

    if desired_bandwidth_Mhz not in available_bandwidth:
        print(f"Bandwidth {desired_bandwidth_Mhz} MHz is not possible !!!!")
        exit()

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
    print("Possible link budget models:")
    print("1 = Datasheet ")
    print("2 = Modified Shannon")
    link_budget_model = int(input("Choice of link budget model: "))
    print()

    if link_budget_model== 1:

        schemes = lookup_table[desired_bandwidth_Mhz]
        data_rates = [v["data_rate"] for v in schemes.values()]
        print("Transmit power is automatically chosen as datasheet is chosen ")
        print(f"Datasheet datarates are {data_rates} Mbps")
        data_rate_Mbps = float(input("Choice data rate: "))
        print()

        if data_rate_Mbps not in data_rates:
            print(f"Data rate {data_rate_Mbps} Mbps not possible !!!!")
            exit()

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
    else:
        print("No this is not a possible link budget")
        exit()  

    dist_comm = dist_comm_calc(
        transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
        received_power_dbm=metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"],
        freq_Mhz=freq_Mhz,
        margin_loss_db=metadata["MARGIN_LOSS"]
    )

    return dist_comm,use_lookup_table

def main():
    ###############################################################################
    #__________________________ TEST PARAMETERS __________________________________#
    ###############################################################################
    # dimensions of area
    length = 30000
    width = 10000
    drone_height = 500
    device_height = 1
    scale_factor = 1
    test_dim = (length*scale_factor, width*scale_factor)
    test_samples = (30, 10)                           # number of sample points on area (x, y)

    test_tolerances = np.arange(10, 15, 5)          #tolerance in meters (min, max, stepsize) 
    test_dist_redundancy = 0                         # distance redundancy for drone placement
    test_dropout_rates = np.arange(0.05, 0.1, 0.05)      #dropout rate in percentage (min, max, stepsize)
    test_dropout_iters = 10                          # number of iterations for each dropout rate (used for histogram)
    
    # wireless communication parameters for MM8108-MF15457 lookup table
    wireless_prefix = ""


    # for either wifi halow, or wifi 7
    # REMEMBER TO CHECK THIS SO RIGHT TO DATASHEET, IF CHECKING FIT

    
    # WIFI HALOW PAREMETERS
    
    # desired_bandwidth_Mhz = 8
    # desired_rate_Mbps = 20
    # freq_Mhz = 868
    # transmit_power_dbm = 22
    # lookup_table_name = "WIFI_HALOW_MM8108"
    # lookup_table = lookup_table_halow_module_MM8108

    # desired_bandwidth_Mhz = 2
    # desired_rate_Mbps = 7.2
    # freq_Mhz = 868
    # transmit_power_dbm = 20
    # lookup_table_name = "WIFI_HALOW_MM8108"
    # lookup_table = lookup_table_halow_module_MM8108

    # WIFI 7 PARAMETERS

    # desired_bandwidth_Mhz = 20
    # desired_rate_Mbps = 13
    # freq_Mhz = 6000
    # transmit_power_dbm = 22
    # lookup_table_name = "WIFI_7_GI0_8_OFDM"
    # lookup_table = lookup_table_wifi7_eht_GI0_8_OFDM
    


    margin_loss_db = 3                                  # safety variable for "other" losses




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
    metadata["TOLERANCES"] = str(test_tolerances)
    metadata["DROPOUT_RATES"] = str(test_dropout_rates)
    metadata["DISTANCE_REDUNDANCY"] = test_dist_redundancy

    #metadata["FREQ_MHZ"] = freq_Mhz
    # metadata[f"{wireless_prefix}TRANSMIT_POWER"] = transmit_power_dbm
    metadata["MARGIN_LOSS"] = margin_loss_db

    # Save dropout iterations used for histogram
    metadata["DROPOUT_ITERATIONS"] = test_dropout_iters

    # Calculate values for modelling wireless commmunication from wifi halow module
    # These values are the same for all grid types

    print("Choose WIFI scheme:")
    print("1 = WIFI 7 ")
    print("2 = WIFI Halow")

    wifi_module = int(input("Enter number: "))
    print()

    if wifi_module == 1:
        dist_comm,use_lookup_table = inputs_define(test_grid_meta_prefix = test_grid_meta_prefix,
                      wireless_prefix=wireless_prefix,
                      lookup_table=lookup_table_wifi7_eht_GI0_8_OFDM,
                      lookup_table_name = "WIFI_7_GI0_8_OFDM",
                      metadata=metadata,
                      freq_Mhz = 6000,
                      enable_graph_plots=True)


    elif wifi_module == 2:
        dist_comm,use_lookup_table = inputs_define(test_grid_meta_prefix = test_grid_meta_prefix,
                      wireless_prefix=wireless_prefix,
                      lookup_table=lookup_table_halow_module_MM8108,
                      lookup_table_name = "WIFI_HALOW_MM8108",
                      metadata=metadata,
                      freq_Mhz = 868,
                      enable_graph_plots=True)
    
    else:
        print("No this is not a possible option !!!!")
        exit()  


    print(f"The range is calculate to be {dist_comm} [m]")



    # have to be after dont overate datarate in metadata
    '''
    graph_sensitivity_phyrate(metadata=metadata,
                                  file_folder_path=f"./{test_grid_meta_prefix}_mesh_design_out/graph",
                                  filename=f"sensivity_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
                                  desired_bandwidth_Mhz=desired_bandwidth_Mhz,
                                  lookup_table=lookup_table,
                                  lookup_table_name=lookup_table_name,
                                  enable_plot = graph_plots
                                  )

    graph_range_phyrate(metadata=metadata,
                            file_folder_path=f"./{test_grid_meta_prefix}_mesh_design_out/graph",
                            filename=f"range_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
                            desired_bandwidth_Mhz=desired_bandwidth_Mhz,
                            lookup_table=lookup_table,
                            lookup_table_name=lookup_table_name,
                            enable_plot = graph_plots)


    shannon_mod_receive_sens_strict = shannon(  metadata = metadata,
                                                data_rate_Mbps=desired_rate_Mbps,
                                                bandwidth_Mhz=desired_bandwidth_Mhz,
                                                noise_figure_db=3,
                                                eta=metadata["ETA_STRICT"],
                                                snr_eff=metadata["SNR_EFF_STRICT"],
                                                wireless_prefix=wireless_prefix
                                            )
    '''

    # get_halow_module_MM8108_params(wireless_prefix=wireless_prefix,
    #                                desired_bandwidth_Mhz=desired_bandwidth_Mhz,
    #                                desired_rate_Mbps=desired_rate_Mbps)

    # for checking given a distance what do i get as the datarate
    # data_rate_mbps = data_rate_given_dist_comm(distance_m=30000,
    #                                            bandwidth_Mhz=metadata[f"{wireless_prefix}BANDWIDTH"],
    #                                            transmit_power_dbm=metadata[f"{wireless_prefix}TRANSMIT_POWER"],
    #                                            margin_loss_db=margin_loss_db,
    #                                            freq_Mhz = metadata["FREQ_MHZ"] )
    # print(f"{data_rate_mbps=}")

    '''
    dist_comm = dist_comm_calc(transmit_power_dbm=transmit_power_dbm,
                               received_power_dbm=shannon_mod_receive_sens_strict,
                               freq_Mhz=freq_Mhz,
                               margin_loss_db=margin_loss_db)
    '''

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
                       tolerances=test_tolerances,
                       drone_distance_redundancy=test_dist_redundancy,
                       dropout_rates=test_dropout_rates,
                       dropout_iters=test_dropout_iters,
                       hist_plot= True,
                       margin_loss_db=margin_loss_db,
                       device_grid=device_grid,
                       link_budget_model = use_lookup_table,
                       grid_func=test_grid_func,
                    )

if __name__ == "__main__":
    main()
