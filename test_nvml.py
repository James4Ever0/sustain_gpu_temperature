# import pynvml

# TARGET_TEMP = 65
# MAX_POWER_LIMIT_RATIO = 0.8

# pynvml.nvmlInit()

# # TODO: figure out how to set and get target temperature

# def get_device_indices():
#     num_gpus = pynvml.nvmlDeviceGetCount()
#     ret = list(range(num_gpus))
#     return ret


# def get_current_stats(device_index: int):
#     handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)

#     info = pynvml.nvmlDeviceGetUtilizationRates(handle)
#     power_info = pynvml.nvmlDeviceGetEnforcedPowerLimit(handle)
#     temp_info =  pynvml.nvmlDeviceGetTemperatureThreshold(handle, pynvml.NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR)
#     return info, power_info, temp_info


# def get_target_power_limit(device_index:int):
#     pynvml.nvmlInit()
#     handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
#     default_power_limit = pynvml.nvmlDeviceGetPowerManagementDefaultLimit(handle)
#     ret = int(default_power_limit * MAX_POWER_LIMIT_RATIO)
#     return ret

# def set_stats(device_index: int):
#     pynvml.nvmlInit()
#     handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)

#     new_power_limit = get_target_power_limit(device_index)

#     pynvml.nvmlDeviceSetPowerManagementLimit(handle, new_power_limit)
#     pynvml.nvmlDeviceSetTemperatureThreshold(
#         handle, pynvml.NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR, TARGET_TEMP
#     )

#     pynvml.nvmlDeviceSetPersistenceMode(handle, 1)


# def verify_stats(device_index: int):
#     info, power_info, temp_info = get_current_stats(device_index)
#     power_limit_set = power_info == get_target_power_limit(device_index)
#     temp_limit_set = temp_info == TARGET_TEMP
#     handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
#     persistent_mode = pynvml.nvmlDeviceGetPersistenceMode(handle)
#     persistent_mode_set = persistent_mode == 1

#     return power_limit_set and temp_limit_set and persistent_mode_set

# def main():
#     pynvml.nvmlInit()
#     for index in get_device_indices():
#         all_set = verify_stats(index)

#         if all_set:
#             print("Power limit and temperature threshold are already set correctly.")
#         else:
#             set_stats(index)
#             print("Power limit and temperature threshold have been adjusted.")
#             assert verify_stats(index), "GPU config verification failed"

from lib import NVMLGPUStatSustainer


def test():
    NVMLGPUStatSustainer().main()


if __name__ == "__main__":
    test()
