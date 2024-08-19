# import subprocess
# import xmltodict
# from typing import Optional
# import os

# TARGET_TEMP = 65
# MAX_POWER_LIMIT_RATIO = 0.8
# NVIDIA_SMI = "nvidia-smi"
# ENCODING = "utf-8"
# EXEC_TIMEOUT = 5

# # check for root permission

# def is_root():
#     ret = os.geteuid()==0
#     return ret

# def get_device_indices():
#     data = get_current_stats()
#     num_gpus = int(data['attached_gpus'])
#     ret = list(range(num_gpus))
#     return ret


# def get_current_stats():
#     cmdlist = prepare_nvidia_smi_command(["-x", "-q"])
#     output = subprocess.check_output(cmdlist).decode(ENCODING)
#     data = xmltodict.parse(output)
#     data = data['nvidia_smi_log']
#     if type(data['gpu']) != list:
#         data['gpu'] = [data['gpu']]

#     return data

# def prepare_nvidia_smi_command(suffix:list[str], device_id:Optional[int] = None):
#     cmdlist = [NVIDIA_SMI]
#     if device_id is not None:
#         cmdlist.extend(['-i', str(device_id)])
#     cmdlist.extend(suffix)
#     print('[*] Prepared NVIDIA-SMI command:', cmdlist)
#     return cmdlist

# def execute_nvidia_smi_command(suffix:list[str],device_id:Optional[int]=None,timeout=EXEC_TIMEOUT):
#     cmdlist = prepare_nvidia_smi_command(suffix, device_id)
#     subprocess.run(cmdlist, timeout=timeout)

# def parse_number(power_limit_string:str):
#     ret = float(power_limit_string.split(" ")[0])
#     ret = int(ret)
#     return ret

# def get_default_power_limit(device_id:int):
#     data = get_current_stats()
#     ret = parse_number(data['gpu'][device_id]["gpu_power_readings"]["default_power_limit"])
#     return ret

# def get_target_power_limit(device_id:int):
#     default_power_limit = get_default_power_limit(device_id)
#     ret = int(MAX_POWER_LIMIT_RATIO*default_power_limit)
#     return ret
# def set_stats(device_id:int):
#     power_limit = get_target_power_limit(device_id)
#     suffix_list = [
#         ["-pl", str(power_limit)],
#         ["-gtt", str(TARGET_TEMP)],
#         ["-pm", "1"]
#     ]
#     for it in suffix_list:
#         execute_nvidia_smi_command(it,device_id=device_id)

# def verify_stats(device_id:int):
#     data = get_current_stats()

#     power_limit = parse_number(data["gpu"][device_id]["gpu_power_readings"]["current_power_limit"])
#     temp_limit = parse_number(data["gpu"][device_id]["temperature"]["gpu_target_temperature"])
#     persistent_mode = data['gpu'][device_id]['persistence_mode']

#     power_limit_set = power_limit == get_target_power_limit(device_id)
#     temp_limit_set = temp_limit == TARGET_TEMP
#     persistent_mode_set = persistent_mode == 'Enabled'

#     return power_limit_set and temp_limit_set and persistent_mode_set


# def main():
#     assert is_root(), "You must be root to execute this script"
#     for index in get_device_indices():
#         print(f"Checking GPU #{index}")
#         all_set = verify_stats(index)

#         if all_set:
#             print("Power limit and temperature threshold are already set correctly.")
#         else:
#             set_stats(index)
#             print("Power limit and temperature threshold have been adjusted.")
#             assert verify_stats(index), "GPU config verification failed"

from lib import NVSMIGPUStatSustainer


def test():
    sustainer = NVSMIGPUStatSustainer()
    sustainer.main()


if __name__ == "__main__":
    test()
    # print(get_current_stats())
