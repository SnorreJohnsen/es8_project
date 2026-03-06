import numpy as np
import math

# metadata = {}

def distance_calc(dist_comm: float,
                  tolerance: float,
                  dist_redundancy: float) -> float:

    distance = dist_comm - tolerance - dist_redundancy

    return distance

# Shannon for calculating received power (not in used due to datasheet is used instead)
def shannon(metadata: dict,
            data_rate_Mbps: float,
            bandwidth_Mhz: float = 4,
            noise_figure_db: float = 6,
            snr_eff: float = 1,
            eta: float = 1,
            wireless_prefix: str ="") -> float:
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

    metadata[f"{wireless_prefix}RECEIVED_SENSITIVITY"] = received_power_dbm
    metadata[f"{wireless_prefix}DATA_RATE"] = data_rate_Mbps
    metadata[f"{wireless_prefix}BANDWIDTH"] = bandwidth_Mhz

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
                                   metadata: dict,
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
