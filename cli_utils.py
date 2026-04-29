import argparse
from plot_utils import (graph_sensitivity_phyrate, graph_range_phyrate)
from mesh_design_lib import (get_halow_module_MM8108_params, shannon, dist_comm_calc)

def inputs_define(*,
                  dir_origin: str,
                  wireless_prefix: str = '',
                  lookup_table,
                  lookup_table_name,
                  metadata: dict,
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
        file_folder_path=f"{dir_origin}/graph",
        filename=f"sensivity_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
        desired_bandwidth_Mhz=desired_bandwidth_Mhz,
        lookup_table=lookup_table,
        lookup_table_name=lookup_table_name,
        enable_plot=enable_graph_plots
    )

    graph_range_phyrate(
        metadata=metadata,
        file_folder_path=f"{dir_origin}/graph",
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
            print(f"Warning: NOT A LINK BUDGET OPTION: {link_budget_model}")
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
                        print(f"Warning: NOT A DATA RATE IN DATASHEET IN WIFI_HALOW_MM8108: {data_rate_Mbps} Mbps")
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
                    dir_origin: str,
                    wireless_prefix: str = '',
                    lookup_table: dict,
                    lookup_table_name: str,
                    desired_bandwidth_Mhz: float,
                    data_rate_Mbps: float,
                    freq_Mhz: float,
                    enable_graph_plots: bool = True,
                    link_budget_model: str,
                    transmit_power_dbm: float,
                    metadata: dict):
    
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
    file_folder_path=f"{dir_origin}/graph",
    filename=f"sensivity_vs_phyrate_bandwidth{desired_bandwidth_Mhz}_MHz_{lookup_table_name}",
    desired_bandwidth_Mhz=desired_bandwidth_Mhz,
    lookup_table=lookup_table,
    lookup_table_name = lookup_table_name,
    enable_plot=enable_graph_plots
    )

    graph_range_phyrate(
        metadata=metadata,
        file_folder_path=f"{dir_origin}/graph",
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

def parse_arguments(default_dir: str):

    parser = argparse.ArgumentParser(
        description="Example CLI",
        formatter_class=argparse.RawTextHelpFormatter  # <- preserves newlines
        )
    
    parser.add_argument("-g", "--grid", type=str, default=None,
                        help="Grid type: square or triangle")
    
    parser.add_argument("-d","--debugplots", action="store_true",
                        help="Enable debug plots")
    
    parser.add_argument("-w", "--wifi", type=str, default=None,
                        help="WiFi module: halow or 7")
    
    parser.add_argument("-b","--bandwidth", type = float, 
                        help = "WiFi halow options: [2, 4, 8], WiFi 7 options: [20]")
    
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
    parser.add_argument("-p","--root_path", type = str,
                        help = f"Set custom root path. Default = {default_dir}")
    
    return parser.parse_args()