import os
import numpy as np
import json
from dataclasses import dataclass, asdict

from mesh_design_lib import (data_rate_given_dist_comm, shannon, dist_comm_calc)

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
    phyrate_mbps: str
    loss_percent: str

###############################################################################
#__________________________ NETWORK CONNECTIVITY______________________________#
###############################################################################

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
                                         metadata: dict,
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
    pass

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
    --------
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
              metadata: dict,
              eta: float = 0.79,
              snr_eff: float = 0.14,
              threshold_link: float = 0,
              tolerance: float,
              use_lookup_table: bool = False) -> list[Link]:

    """
    Docstring for link_list

    Inputs:
    -------
    nodes: list of sorted N Node classes of drone IDs and positions
    dist_comm: Theoretical communication distance of drone in meters
    margin_loss_db: float, Additional loss margin in dB applied to the link budget.
    eta: float, Spectral efficiency factor used in the Shannon calculation.
    snr_eff: float, Effective signal-to-noise ratio used in the Shannon calculation.
    threshold_link: float,
    use_lookup_table: bool for using lookup table (True for datasheet, False for shannon)

    Returns:
    --------
    links: list of N Link classes with sources and respective targets
    num_links_video: List containing the number of valid outgoing links per node for video communication.
    num_links_cmd: List containing the number of valid outgoing links per node for command/control communication.
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
            t = tolerance * 2
            d = np.sqrt(distances)
            distances += 2 * d * t + t**2
            if use_lookup_table == False:
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
                             count_cmd=count_cmd,
                             metadata=metadata
                             )
            else:
                links, count, count_cmd = link_datasheet(distance_sq =distances,
                                                                          links = links,
                                                                          target = target,
                                                                          source = source,
                                                                          threshold_link=threshold_link,
                                                                          count = count,
                                                                          count_cmd=count_cmd,
                                                                          metadata=metadata)
         
        num_links_video.append(count)
        num_links_cmd.append(count_cmd)
        
    return links, num_links_video, num_links_cmd

def link_shannon(distance_sq: float,
                 eta: float,
                 snr_eff: float,
                 margin_loss_db: float,
                 links: list,
                 target,
                 source,
                 threshold_link: float,
                 count: int,
                 count_cmd: int,
                 metadata: dict,
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

    distance = np.sqrt(distance_sq)

    data_rate_mbps = data_rate_given_dist_comm(distance_m=distance,
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
                            phyrate_mbps=f"{data_rate_mbps:.2f}",
                            loss_percent="10") # 10%
                
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
                   metadata: dict,
                   wireless_prefix: str = ""):
    
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
                    phyrate_mbps=f"{data_rate_mbps:.2f}",
                    loss_percent="10") # 10%
                    #   data_rate=str(metadata[f"{wireless_prefix}DATA_RATE"]))
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
                      extra: dict,
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
    network['metadata'] = extra
    network["nodes"] = [asdict(i) for i in nodes]
    network["links"] = [asdict(j) for j in links]

    with open(os.path.join(file_folder_path, file_name), "w") as f:
        json.dump(network, f)
