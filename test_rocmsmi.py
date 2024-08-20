# from lib import ROCMSMIGPUStatSustainer

# for tuning this stuff we need to run gpu benchmark over each gpu, 100% util

# get gpu clocks: --showgpuclocks
# get default power consumption: --showmaxpower
# set power overdrive in watt: --setpoweroverdrive
# --showgpuclocks
# --showclkfrq Show supported GPU and Memory Clock
# get temperature:  --showtemp
# output json: --json
# --setperflevel manual

# ref: https://github.com/pr0d1r2/linux-systemd-amdgpu-adaptive-thermal-limiter

# note: we do not change the mem clock levels

# def test():
#     ROCMSMIGPUStatSustainer().main()

from typing import Optional
import subprocess
import json
import time

EXECUTE_TIMEOUT=5
TEMP_LIMIT = 65

def generate_rocm_cmdline(suffixs:list[str], device_id:Optional[int], export_json:bool):
    cmdline = ['rocm-smi']
    if device_id is not None:
        cmdline += ['-d', str(device_id)]
    cmdline += suffixs
    if export_json:
        cmdline += ['--json']
    print('[*] Generated cmdline:', cmdline)
    return cmdline

def execute_rocm_cmdline(suffixs:list[str], device_id:Optional[int]= None, export_json=True, timeout=EXECUTE_TIMEOUT):
    cmdline = generate_rocm_cmdline(suffixs, device_id =device_id, export_json=export_json)
    output = subprocess.check_output(cmdline,timeout=timeout)
    if export_json:
        output = json.loads(output)
    return output

def get_gpu_sclk_min_max_levels(device_id:int):
    data:dict = execute_rocm_cmdline(['-s'], device_id)
    level_data = get_first_value_from_dict(data)
    levels = [int(it) for it in level_data.keys()]
    min_level, max_level = min(levels), max(levels)
    return min_level, max_level

def get_gpu_current_sclk_level(device_id:int):
    data:dict = execute_rocm_cmdline(['-c'], device_id=device_id)
    level_data = get_first_value_from_dict(data)
    ret = int(level_data['sclk_clock_level:'])
    return ret

def get_device_indices():
    data:dict = execute_rocm_cmdline(["--showtopo"])
    # count for keys
    device_count = len(data.keys())
    ret = list(range(device_count))
    return ret

def get_first_value_from_dict(data:dict):
    ret = list(data.values())[0]
    return ret

def set_gpu_sclk_level(device_id:int, sclk_level:int):
    execute_rocm_cmdline(['--setsclk', str(sclk_level)], device_id=device_id)

def set_gpu_as_manual_perf_level(device_id:int):
    execute_rocm_cmdline(['--setperflevel', 'manual'], device_id=device_id)

def get_gpu_temperature(device_id:int):
    data:dict= execute_rocm_cmdline(['-t'], device_id=device_id)
    temp_data = get_first_value_from_dict(data)
    ret = 0
    for name, value in temp_data.items():
        try:
            value = float(value)
            ret = max(value, ret)
        except ValueError:
            print(f'[-] Failed to convert value "{value}" ({name}) to float')
    return ret

def mainloop():
    for it in get_device_indices():
        set_gpu_as_manual_perf_level(it)
        gpu_temp = get_gpu_temperature(it)
        current_sclk_level = get_gpu_current_sclk_level(it)
        min_sclk_level, max_sclk_level = get_gpu_sclk_min_max_levels(it)
        if gpu_temp > TEMP_LIMIT:
            new_sclk_level = current_sclk_level -1
            new_sclk_level = max(min_sclk_level, new_sclk_level)
        else:
            new_sclk_level = current_sclk_level +1
            new_sclk_level = min(max_sclk_level, new_sclk_level)
        set_gpu_sclk_level(it,new_sclk_level)

def main():
    while True:
        mainloop()
        time.sleep(1)

if __name__ == "__main__":
    # test()
    main()
