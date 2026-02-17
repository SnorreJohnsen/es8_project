import numpy as np
import matplotlib.pyplot as plt
import math
import os
from tqdm import tqdm
import random

random.seed(0)

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

def distance_calc(dist_comm: float, 
                  tolerances_input: tuple[float, float, float], 
                  dist_redundancy: float) -> np.ndarray:
    distance = []

    tol_min, tol_max, tol_step = tolerances_input

    tolerances = np.linspace(tol_min, tol_max, tol_step)
    

    distance = dist_comm - tolerances - dist_redundancy

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

def get_halow_module_MM8108_params(desired_bandwidth_Mhz, desired_rate_Mbps):
    # Find closest available bandwidth
    available_bandwidth = np.array(list(lookup_table_halow_module_MM8108.keys()))
    bandwidth_index = np.argmin(np.abs(available_bandwidth - desired_bandwidth_Mhz))
    closest_bandwidth = int(available_bandwidth[bandwidth_index])

    # Get all MCS schemes for that bandwidth
    schemes = lookup_table_halow_module_MM8108[closest_bandwidth].values()

    # Find the sorted_scheme with data_rate closest to desired_rate_Mbps
    sorted_schemes = sorted(schemes, key=lambda s: abs(s['data_rate'] - desired_rate_Mbps))

    # Find first sorted_scheme >= desired datarate
    for best_scheme in sorted_schemes:
        if best_scheme['data_rate'] >= desired_rate_Mbps:
            best_data_rate = best_scheme['data_rate']
            best_rx_sens = best_scheme['receive_sensitivity']
            best_tx_power = best_scheme['transmit_power']
            break
        else:
            # If desired data rate above all availeble schemes return highest sorted_scheme
            best_scheme = sorted_schemes[0]
            best_data_rate = best_scheme['data_rate']
            best_rx_sens = best_scheme['receive_sensitivity']
            best_tx_power = best_scheme['transmit_power']

    return best_data_rate, best_rx_sens, best_tx_power, closest_bandwidth

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


def plot_drone_positions(grid_name: str,
                         drone_positions: np.ndarray, 
                         distance: float,
                         dist_comm: float,
                         dim: tuple[float, float],
                         sample_resolution: tuple[int, int],
                         file_path_folder: str,
                         drone_dropout: float):
    x_dim, y_dim = dim
    x_sample_res, y_sample_res = sample_resolution
    font_size = 8

    fig, ax = plt.subplots()

    # Stating number of drones in mesh
    num_drones = len(drone_positions) 

    if drone_dropout > 0:
        num_drones_dropout = math.ceil(num_drones * drone_dropout)
        drone_dropout_perc_real = num_drones_dropout/num_drones # Calculating actual dropout percentage for plot
        num_drones = num_drones - num_drones_dropout

        # Removing drones from drone positions in relation to dropout
        np.random.shuffle(drone_positions)
        drone_positions = drone_positions[:-num_drones_dropout, :]
    
    


    # Plot drone positions as dots
    x_pos = drone_positions[:, 0]
    y_pos = drone_positions[:, 1]
    ax.plot(x_pos, y_pos, 'o', color = 'red', markersize=2)

    counts_inside = []

    for i, (x, y) in enumerate(drone_positions):
        # Compute distances from drone i to all drones
        distances = (drone_positions[:, 0] - x)**2 + (drone_positions[:, 1] - y)**2
        
        # Count how many are within dist_comm (exclude itself)
        count = np.sum(distances <= (dist_comm+1)**2) - 1
        counts_inside.append(count)

        # Draw communcation dist_comm as circle
        circle = plt.Circle((x, y), dist_comm, fill=True, facecolor='blue', edgecolor='black', alpha=0.1)
        ax.add_patch(circle)

    counts_inside = np.array(counts_inside)

    min_drones_inside = np.min(counts_inside)
    #max_drones_inside = np.max(counts_inside) #commented out since its not used in plot fig
    avg_drones_inside = np.mean(counts_inside)

    # Device points in drone area
    x_device_points = np.linspace(0, x_dim, x_sample_res)
    y_device_points = np.linspace(0, y_dim, y_sample_res)

    valid_connection_counts = []

    for x_new in tqdm(x_device_points, desc=f"Computing distances for {grid_name} mesh"):
        for y_new in y_device_points:
            # Compute distances from device i to all drones
            distances = (drone_positions[:, 0] - x_new)**2 + (drone_positions[:, 1] - y_new)**2

            # Add connections to valid connection count
            connections = np.sum(distances <= dist_comm**2)

            valid_connection_counts.append(connections)

    valid_connection_counts = np.array(valid_connection_counts)

    min_device_connections = np.min(valid_connection_counts)
    avg_device_connections = np.mean(valid_connection_counts)

    title_text = (
    f"{grid_name} Mesh, Drones = {num_drones}, d = {distance:.2f} [m], dist_comm = {dist_comm:.2f} [m], Dropout(%) = {drone_dropout_perc_real:.3f}, Dropout(#) = {num_drones_dropout} \n"
    f"Drone connections: Min = {min_drones_inside}, Avg = {avg_drones_inside:.2f} \n "
    f"Device connections: Min = {min_device_connections}, Avg = {avg_device_connections:.2f}"
)

    ax.set_title(title_text, fontsize=font_size, pad=10)  # pad adds space above plot
    
    ax.set_xlabel("meters", fontsize=font_size)
    ax.set_ylabel("meters", fontsize=font_size)

    ax.set_aspect('equal', 'box')
    ax.tick_params(axis='both', labelsize=font_size)

    # save fig to file path
    os.makedirs(file_path_folder, exist_ok=True)
    file_path = os.path.join(file_path_folder, f"{grid_name}.png")
    fig.savefig(file_path, dpi=300, bbox_inches='tight')
    plt.close(fig)

################## test variables ###################################
length = 30000
width = 10000
scale_factor = 1

test_dim = (length*scale_factor, width*scale_factor)
samples = (600, 200)
file_folder = "./mesh_design_out"

test_tolerances = (100, 300, 3) #tolerances in meters (min, max, steps)
test_dist_redundancy = 0
dropout = 0.1

desired_bandwidth_Mhz = 8
desired_rate_Mbps = 20
freq_Mhz = 868
margin_loss_db = 3
###################################################################

data_rate, received_power_dbm, transmit_power_dbm, bandwidth = get_halow_module_MM8108_params(desired_bandwidth_Mhz=desired_bandwidth_Mhz, desired_rate_Mbps=desired_rate_Mbps)
print(f"{data_rate=},{received_power_dbm=}, {transmit_power_dbm=}, {bandwidth=}")

dist_comm = dist_comm_calc(transmit_power_dbm=transmit_power_dbm, 
                           received_power_dbm=received_power_dbm, 
                           freq_Mhz=freq_Mhz,
                           margin_loss_db=margin_loss_db)
print(f"{dist_comm=}")


test_distance = distance_calc(dist_comm, test_tolerances, test_dist_redundancy)


for i in range(test_tolerances[2]):
    drone_pos_sq = drone_sq_grid(test_dim, test_distance[i])
    plot_drone_positions(f"Square_{i}", 
                        drone_pos_sq, 
                        distance=test_distance[i], 
                        dist_comm=dist_comm, 
                        dim=test_dim, 
                        sample_resolution=samples, 
                        file_path_folder=file_folder,
                        drone_dropout=dropout)


"""
drone_pos_hex = drone_hex_grid(test_dim, test_distance, extra_edge_drones = False)
plot_drone_positions("Hexagonal", 
                     drone_pos_hex, 
                     distance=test_distance, 
                     dist_comm=test_dist_comm, 
                     dim=test_dim, 
                     sample_resolution=samples, 
                     file_path_folder=file_folder)

drone_pos_hex_diamond = drone_hex_diamond_grid(test_dim, test_distance)
plot_drone_positions("Hexagonal-diamond", 
                     drone_pos_hex_diamond, 
                     distance=test_distance, 
                     dist_comm=test_dist_comm, 
                     dim=test_dim, 
                     sample_resolution=samples, 
                     file_path_folder=file_folder)

drone_pos_hex_squished = drone_hex_grid_squished(test_dim, test_distance)
plot_drone_positions("Hexagonal-squished", 
                     drone_pos_hex_squished, 
                     distance=test_distance, 
                     dist_comm=test_dist_comm, 
                     dim=test_dim, 
                     sample_resolution=samples, 
                     file_path_folder=file_folder)
                   
drone_pos_tri = drone_triangle_grid(test_dim, test_distance)
plot_drone_positions("Triangle", 
                     drone_pos_tri, 
                     distance=test_distance, 
                     dist_comm=test_dist_comm, 
                     dim=test_dim, 
                     sample_resolution=samples, 
                     file_path_folder=file_folder)

"""
