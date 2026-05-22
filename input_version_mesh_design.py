import numpy as np
import os
from tqdm import tqdm
import json
from mesh_design_lib import (distance_calc,
                             lookup_table_halow_module_MM8108,
                             lookup_table_wifi7_eht_GI0_8_OFDM,
                             lookup_table_wifi7_eht_GI3_2_OFDMA)
from drone_grids import (drone_sq_grid,
                         drone_triangle_grid)
from cli_utils import (parse_arguments,
                       inputs_define,
                       argument_define)
from plot_utils import (plot_drone_positions,
                        plot_drone_links,
                        link_matrix,
                        plot_histogram_drone_links,
                        calculate_device_links)
from link_utils import (node_list,
                        link_list,
                        make_json_network,
                        checking_max_phyrate_fully_connected)

metadata = dict()

###############################################################################
#__________________________ HELPER FUNCTIONS _________________________________#
###############################################################################

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

###############################################################################
#___________________________ EXECUTIVE FUNCTIONS _____________________________#
###############################################################################

def process_drone_mesh(*,
                       grid_prefix: str,
                       dir_origin: str,
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

    # Directory Root (dir_origin) used for jsons and plots
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
        drone_distance = distance_calc(dist_comm, tolerance, drone_distance_redundancy) #with tolerance
        print(f'Distance between drones: {drone_distance}')

        # Choose grid function
        all_drone_positions = grid_func(dim=dim, dist=drone_distance, **kwargs)

        z_row = np.full((all_drone_positions.shape[0], 1), drone_height)
        all_drone_positions = np.hstack((all_drone_positions, z_row))

        # For loop over number of dropouts'
        if len(dropout_rates) > 0:
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
                                                                    metadata=metadata,
                                                                    eta=metadata["ETA_STRICT"],
                                                                    snr_eff=metadata["SNR_EFF_STRICT"],
                                                                    threshold_link=threshold_link_mbps,
                                                                    tolerance=tolerance,
                                                                    use_lookup_table=link_budget_model)

                    # Make array of all link counts for partial drone mesh
                    total_link_count_dropout.append(link_count_dropout)
                    total_link_count_dropout_cmd.append(link_count_dropout_cmd)
                    # Check if the remaining network after dropout is fully connected
                    if debug_plots == True:
                        reachable_phyrate = checking_max_phyrate_fully_connected(nodes=node_list_dropout,
                                                                                dist_comm=dist_comm,
                                                                                base_rate=data_rate_Mbps,
                                                                                metadata=metadata,
                                                                                use_lookup_table=link_budget_model)
                        total_reachable_phyrate = total_reachable_phyrate + reachable_phyrate
                        reachable_phyrates.append(reachable_phyrate)

                if debug_plots == True:
                    # Calculate the connected percentage of given dropout mesh
                    metadata[f"{grid_prefix}_{j}_FULLY_CONNECTED_PHYRATE_AVERAGE"] = total_reachable_phyrate / dropout_iters
                    metadata[f"{grid_prefix}_{j}_FULLY_CONNECTED_PHYRATE_MIN"] = min(reachable_phyrates)
                    metadata[f"{grid_prefix}_{j}_FULLY_CONNECTED_PHYRATE_MAX"] = max(reachable_phyrates)

                # Metaprefix for file names
                prefix_dropout_real_perc = metadata[f"{grid_prefix}_{j}_DROPOUT_REAL_PERCENTAGE"]

                num_nodes_dropout = len(node_list_dropout)
                
                extra = metadata.copy()
                if "DATA_RATE" in extra:
                    del extra["DATA_RATE"]

                # Make single network of each dropout rate
                make_json_network(file_name=f"{grid_prefix}_{num_nodes_dropout}_nodes.json",
                                file_folder_path=dir_origin_partial_json,
                                extra=extra,
                                nodes=node_list_dropout,
                                links=link_list_dropout)

            # Calculating links from devices to drones for partial drone mesh
            if debug_plots == True:
                dist_device_to_drone= calculate_device_links(meta_prefix= f"{grid_prefix}_{j}_DROPOUT_",
                                    nodes=node_list_dropout,
                                    dist_comm=dist_comm,
                                    metadata=metadata,
                                    device_positions=device_grid)

                # Histogram and drone position plots over total iterations
                video_rate= metadata["histogram_high_rate"]
                cmd_rate= metadata["histogram_low_rate"]
                plot_histogram_drone_links(file_name=f"{grid_prefix}_video_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_histogram_{num_nodes_dropout}_nodes.png",
                                                title_name=f"{grid_prefix} Video {video_rate} [Mb/s] Histogram \n Dropout = {prefix_dropout_real_perc*100:.2f}% Tolerance = {tolerance} [m]",
                                                drone_link_count=total_link_count_dropout,
                                                iterations=dropout_iters,
                                                file_folder_path=dir_origin_partial_plots)
                plot_histogram_drone_links(file_name=f"{grid_prefix}_command_{prefix_dropout_real_perc:.2f}_dropout_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_histogram_{num_nodes_dropout}_nodes.png",
                                                title_name=f"{grid_prefix} Command {cmd_rate} [Mb/s] Histogram \n Dropout = {prefix_dropout_real_perc*100:.2f}% Tolerance = {tolerance} [m]",
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
                                    use_lookup_table=link_budget_model,
                                    metadata=metadata)
                
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
                                                  metadata=metadata,
                                                  eta=metadata["ETA_STRICT"],
                                                  snr_eff=metadata["SNR_EFF_STRICT"],
                                                  threshold_link=threshold_link_mbps,
                                                  tolerance=tolerance,
                                                  use_lookup_table=link_budget_model)

        # Add number drones used in full mesh to metadata
        metadata[f"{grid_prefix}_ALL_NUMBER_DRONES"] = len(node_list_all)
        num_nodes = len(node_list_all)

        extra = metadata.copy()
        if "DATA_RATE" in extra:
            del extra["DATA_RATE"]

        # Make the json network from list of nodes
        make_json_network(file_name=f"{grid_prefix}_{num_nodes}_nodes.json",
                          file_folder_path=dir_origin_full_json,
                          extra=extra,
                          nodes=node_list_all,
                          links=link_list_all)

        if debug_plots == True:
            # Calculating links from devices to drones for full drone mesh
            dist_device_to_drone_full = calculate_device_links(meta_prefix=f"{grid_prefix}_ALL_",
                                nodes=node_list_all,
                                dist_comm=dist_comm,
                                metadata=metadata,
                                device_positions=device_grid)
            
            video_rate= metadata["histogram_high_rate"]
            cmd_rate= metadata["histogram_low_rate"]
            # Histogram and drone position plots over full drone mesh
            plot_histogram_drone_links(file_name=f"{grid_prefix}_video_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_histogram_{num_nodes}_nodes.png",
                                        title_name=f"{grid_prefix} Video {video_rate} [Mb/s] Histogram \n Tolerance = {tolerance} [m]",
                                        drone_link_count=link_count_all,
                                        file_folder_path=dir_origin_full_plots)
            plot_histogram_drone_links(file_name=f"{grid_prefix}_command_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_histogram_{num_nodes}_nodes.png",
                                        title_name=f"{grid_prefix} Command {cmd_rate} [Mb/s] Histogram \n Tolerance = {tolerance} [m]",
                                        drone_link_count=link_count_all_cmd,
                                        file_folder_path=dir_origin_full_plots)
            
            plot_drone_positions(meta_prefix=f"{grid_prefix}_ALL_",
                                wireless_prefix=wireless_prefix,
                                file_name=f"{grid_prefix}_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_full_mesh_{num_nodes}_nodes.png",
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
                                use_lookup_table=link_budget_model,
                                metadata=metadata)
            
            plot_drone_links(title_name=f"{grid_prefix} Mesh | Tolerance = {tolerance} [m]",
                            file_name=f"{grid_prefix}_{tolerance}_tolerance_{data_rate_Mbps}_datarate_Mbps_{bandwidth_Mhz}_bandwidth_Mhz_links_{num_nodes}_nodes.png",
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

if __name__ == "__main__":
    # Set grid type to process
    test_grid_meta_prefix = "Square"
    test_grid_func = drone_sq_grid

    # Directory Root
    default_dir = "/home/aau/meshsim/output"
    base_dir = default_dir
    dir_origin = os.path.join(base_dir, f"{test_grid_meta_prefix}_mesh_design")

    args = parse_arguments(default_dir=default_dir)

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
    test_samples = (30, 10)                             # number of sample points on area (x, y)

    default_tolerances = np.arange(10, 15, 5)           # tolerance in meters (min, max, stepsize) 
    default_margin = 0                                  # distance redundancy for drone placement
    default_dropout_rates = np.arange(0.05,0.20,0.05)   # dropout rate in percentage (min, max, stepsize)
    default_drop_iter = 100                             # number of iterations for each dropout rate (used for histogram)

    # wireless communication parameters for MM8108-MF15457 lookup table
    wireless_prefix = ""
    margin_loss_db = 3 # safety variable for "other" losses

    ###############################################################################
    ###############################################################################

    # Save test parameters to metadata
    metadata["AREA_DIMENSIONS"] = str(test_dim)
    metadata["DRONE_HEIGHT"] = drone_height
    metadata["DEVICE_HEIGHT"] = device_height
    metadata["SAMPLES"] = str(test_samples)
    #metadata["DISTANCE_REDUNDANCY"] = default_margin

    #metadata["FREQ_MHZ"] = freq_Mhz
    # metadata[f"{wireless_prefix}TRANSMIT_POWER"] = transmit_power_dbm
    metadata["MARGIN_LOSS"] = margin_loss_db

    # Save dropout iterations used for histogram
    #metadata["MARGIN"] = str(default_margin)
    #metadata["TOLERANCES"] = str(default_tolerances)
    #metadata["DROPOUT_RATES"] = str(default_dropout_rates)
    #metadata["DROPOUT_ITERATIONS"] = default_drop_iter

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
                test_grid_meta_prefix = "square"
                test_grid_func = drone_sq_grid
                break
            elif grid == 2:
                test_grid_meta_prefix = "triangle"
                test_grid_func = drone_triangle_grid
                break
            else:
                print(f"Warning: NOT A GRID TYPE: {grid}\n")
            
            # Directory Root
            dir_origin = os.path.join(base_dir, f"{test_grid_meta_prefix}_mesh_design")
            #dir_origin = f"./{test_grid_meta_prefix}_mesh_design_out"

        while True:
            print("Choose WiFi scheme:")
            print("1 = WiFi 7 ")
            print("2 = WiFi Halow")
            wifi_module = int(input("Enter number: "))
            print()

            if wifi_module in (1,2):
                break
            else: 
                print(f"Warning: NOT AN AVAILABLE WIFI MODULE: {wifi_module}")
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
                print(f"WARNING: NEED TO SET DEBUG PLOT OFF (1) OR ON (2): NOT {debug_int}\n")

        if wifi_module == 1:
            dist_comm,use_lookup_table = inputs_define(dir_origin=dir_origin,
                                                       wireless_prefix=wireless_prefix,
                                                       lookup_table=lookup_table_wifi7_eht_GI0_8_OFDM,
                                                       lookup_table_name = "WIFI_7_GI0_8_OFDM",
                                                       metadata=metadata,
                                                       freq_Mhz = 6000,
                                                       enable_graph_plots=Enable_debug_plots)

        elif wifi_module == 2:
            dist_comm,use_lookup_table = inputs_define(dir_origin=dir_origin,
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
        margin = args.margin
        tol = args.tolerances
        dropout_iter = args.iterations
        drop_rates = args.dropout_rates
        root_path = args.root_path

        if margin is not None:
            default_margin = margin 
        if tol is not None:
            default_tolerances = np.array([float(x) for x in tol.split(",")])
        if dropout_iter is not None:
            default_drop_iter = dropout_iter
        if drop_rates is not None:
            default_dropout_rates = [float(x) for x in drop_rates.split(",")if float(x) != 0]
            for i, rate in enumerate(default_dropout_rates):
                if rate > 1 and rate <= 100:
                    print(f"\nWARNING: dropout rate {rate} is not in range 0 to 1")
                    default_dropout_rates[i] = rate / 100
                    print(f"EXPECTED: you meant to write {default_dropout_rates[i]}")
                if rate > 100:
                    print(f"\nWARNING: THE RATES ARE SUPPORTED FOR 0.0 to 1.0, {rate} IS NOT WITHIN RANGE")
                    exit()
        print(default_dropout_rates)
        if root_path is not None:
            root_path = os.path.expanduser(root_path)
            valid = True
            if not os.path.isabs(root_path):
                print(f'[ERROR] Path must be absolute: {root_path}')
                valid = False
            if not os.path.isdir(root_path):
                print(f'[ERROR] Directory does not exist: {root_path}')
                valid = False
            if valid:
                base_dir = root_path
                print(f'[INFO] Saving in custom path: {base_dir}')
            else:
                print(f"[INFO] Saving in default path: {default_dir}")
        else:
            print(f'[INFO] Saving in default path: {default_dir}')

        metadata["MARGIN"] = str(default_margin)
        metadata["TOLERANCES"] = str(default_tolerances)
        metadata["DROPOUT_RATES"] = str(default_dropout_rates)
        metadata["DROPOUT_ITERATIONS"] = default_drop_iter
        metadata["MODEL"] = link_budget_model
        metadata["WIFI_MODULE"] = wifi_module
        metadata["SET_DATA_RATE"] = data_rate_Mbps

        print()
        if grid == "square":
            test_grid_meta_prefix = "Square"
            test_grid_func = drone_sq_grid
        elif grid == "triangle":
            test_grid_meta_prefix = "Triangle"
            test_grid_func = drone_triangle_grid
        else:
            print(f"Warning: NOT A GRID TYPE: {grid}\n")
            exit()

        # Directory Root
        dir_origin = os.path.join(base_dir, f"{test_grid_meta_prefix}_mesh_design")

        if wifi_module == "halow":
            freq_Mhz = 868
            dist_comm,use_lookup_table = argument_define(dir_origin=dir_origin,
                                                         wireless_prefix='',
                                                         lookup_table=lookup_table_halow_module_MM8108,
                                                         lookup_table_name="WIFI_HALOW_MM8108",
                                                         desired_bandwidth_Mhz=desired_bandwidth_Mhz,
                                                         data_rate_Mbps= data_rate_Mbps,
                                                         freq_Mhz=freq_Mhz,
                                                         enable_graph_plots=Enable_debug_plots,
                                                         link_budget_model=link_budget_model,
                                                         transmit_power_dbm=transmit_power_dbm,
                                                         metadata=metadata)
        elif wifi_module == "7":
            freq_Mhz = 6000
            dist_comm,use_lookup_table = argument_define(dir_origin=dir_origin,
                                                         wireless_prefix='',
                                                         lookup_table=lookup_table_wifi7_eht_GI0_8_OFDM,
                                                         lookup_table_name="WIFI_7_GI0_8_OFDM",
                                                         desired_bandwidth_Mhz=desired_bandwidth_Mhz,
                                                         data_rate_Mbps= data_rate_Mbps,
                                                         freq_Mhz=freq_Mhz,
                                                         enable_graph_plots=Enable_debug_plots,
                                                         link_budget_model=link_budget_model,
                                                         transmit_power_dbm=transmit_power_dbm,
                                                         metadata=metadata)   
        else:
            print(f"Warning: NOT AN AVAILABLE WIFI MODULE: {wifi_module}")
            exit()

    print(f"The range is calculate to be {dist_comm} [m]")
    if use_lookup_table == True:
        print("\nWarning: using rounded to reference thresholds from lookup table")

    # Both a device_grid and a device_point can be used in process_drone_mesh
    device_point = np.array([[100,100,device_height]])
    device_grid = make_device_grid(dim=test_dim,
                                   z_height=device_height,
                                   sample_resolution=test_samples)

    # Process a drone mesh to give metadata and plots
    process_drone_mesh(grid_prefix=test_grid_meta_prefix,
                       dir_origin=dir_origin,
                       wireless_prefix=wireless_prefix,
                       dist_comm=dist_comm,
                       dim=test_dim,
                       drone_height=drone_height,
                       tolerances=default_tolerances,
                       drone_distance_redundancy=default_margin,
                       dropout_rates=default_dropout_rates,
                       dropout_iters=default_drop_iter,
                       margin_loss_db=margin_loss_db,
                       device_grid=device_grid,
                       link_budget_model=use_lookup_table,
                       debug_plots=Enable_debug_plots,
                       grid_func=test_grid_func)