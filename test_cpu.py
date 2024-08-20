# pid control reference: https://pypi.org/project/PID-Py/
# https://github.com/jluo1875/CPU-Temperature-Throttler

import os, sys, time, argparse
import subprocess, logging, signal
import json
# logging.basicConfig(filename='cpu_throttle.log', level=logging.DEBUG)
# logFormatter = logging.Formatter("%(asctime)s %(filename)s: " + fmt.format("%(levelname)s") + " %(message)s", "%Y/%m/%d %H:%M:%S")
if os.geteuid() != 0:
    exit('You need to run this with root privileges. Please try again with sudo.')
logging.basicConfig(
    level=logging.INFO,
    # level=logging.DEBUG,
    format="%(asctime)s [%(levelname)8s] %(message)s",
    handlers=[
        logging.FileHandler("/var/log/cpu_throttle.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

def get_temperature_readings():
    cmdlist = [
        "sensors",'-j'
    ]
    output = subprocess.check_output(cmdlist, encoding='utf-8')
    ret = json.loads(output)
    return ret

CPU_TEMP_SENSOR_PREFIXS = ["coretemp-",'cpu_thermal',
        'k10temp'
]

def check_prefix_in_strlist(strlist:list[str], prefix:str):
    ret = False
    for it in strlist:
        if it.startswith(prefix):
            ret = True
            break
    return ret

def detect_platform_from_readings(readings:dict):
    reading_keys = list(readings.keys())
    ret = -1
    for index, elem in enumerate(CPU_TEMP_SENSOR_PREFIXS):
        if check_prefix_in_strlist( reading_keys,elem):
            ret = index
            break
    return ret

def filter_by_prefix_and_calculate_max_value_from_readings(readings:dict, prefix:str):
    ret = 0
    for adaptor_name,sensor in readings.items():
        if adaptor_name.startswith(prefix):
            for _, sensor_value in sensor.items():
                if type(sensor_value) is dict:
                    for sensor_value_key, sensor_value_reading in sensor_value.items():
                        if sensor_value_key.endswith("_input"):
                            ret = max(ret, sensor_value_reading)
    return ret

def get_cpu_temperature(hardware):
    readings = get_temperature_readings()
    ret= None
    platform_id = detect_platform_from_readings(readings)
    ret = 0
    if platform_id != -1:
        prefix = CPU_TEMP_SENSOR_PREFIXS[platform_id]
        ret = filter_by_prefix_and_calculate_max_value_from_readings(readings, prefix)*1000
    if int(ret) == 0:
        ret = getTemp(hardware)
    return ret


def getArguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--time', type=int, help='Seconds to cooldown cpu before next check, default is 20 seconds.')
    parser.add_argument('--crit_temp', type=int, help='Temp for cpu to throttle down (temperature in celcius degrees)')
    parser.add_argument('--debug', action='store_true', help='Output more information when set to True.')
    args = parser.parse_args()
    if args.time is None:
        relaxtime = 30 # time in seconds
    else:
        relaxtime = int(args.time)
    if args.crit_temp is None:
        crit_temp = 64000 # temp in mili celcius degree
    else:
        crit_temp = int(args.crit_temp)*1000
    # if args.debug:
    #     logging.getLogger().setLevel(logging.DEBUG)
    # else:
    #     logging.getLogger().setLevel(logging.INFO)
    return relaxtime, crit_temp, args.debug

# determine hardware and kernel types
def hardwareCheck():
# does this work: $ echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
    if os.path.exists("/sys/devices/LNXSYSTM:00/LNXTHERM:00/LNXTHERM:01/thermal_zone/temp") == True:
        return 4
    elif os.path.exists("/sys/bus/acpi/devices/LNXTHERM:00/thermal_zone/temp") == True:
        return 5 # intel
    elif os.path.exists("/sys/class/hwmon/hwmon0") == True:
        return 6 # amd
    elif os.path.exists("/sys/class/thermal/thermal_zone3/")  == True:
        return 7 # intel
    elif os.path.exists("/proc/acpi/thermal_zone/THM0/temperature") == True:
        return 1
    elif os.path.exists("/proc/acpi/thermal_zone/THRM/temperature") == True:
        return 2
    elif os.path.exists("/proc/acpi/thermal_zone/THR1/temperature") == True:
        return 3
    else:
        return 0

# depending on the kernel and hardware config, read the temperature
def getTemp(hardware):
    temp = 0
    if hardware == 6:
        # logging.debug('reading temp..')
        with open("/sys/class/hwmon/hwmon0/temp1_input", 'r') as mem1:
            temp = mem1.read().strip()
    elif hardware == 1:
        temp = open("/proc/acpi/thermal_zone/THM0/temperature").read().strip().lstrip('temperature :').rstrip(' C')
    elif hardware == 2:
        temp = open("/proc/acpi/thermal_zone/THRM/temperature").read().strip().lstrip('temperature :').rstrip(' C')
    elif hardware == 3:
        temp = open("/proc/acpi/thermal_zone/THR1/temperature").read().strip().lstrip('temperature :').rstrip(' C')
    elif hardware == 4:
        temp = open("/sys/devices/LNXSYSTM:00/LNXTHERM:00/LNXTHERM:01/thermal_zone/temp").read().strip().rstrip('000')
    elif hardware == 5:
        with open("/sys/class/thermal/thermal_zone0/temp") as mem1:
            temp = mem1.read().strip()
    elif hardware == 7:
        with open("/sys/class/thermal/thermal_zone3/temp") as mem1:
            temp = mem1.read().strip()
    else:
        return 0
    # logging.debug(f"Temp is {temp}")
    # logging.debug(f"Temp is an integer: {isinstance(temp, int)}")
    temp = float(temp)
    if temp < 1000:
        temp = temp * 1000
    return int(temp)

def getMinMaxFrequencies(hardware):
    if hardware == 0:
        # with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq", 'r') as mem1:
        #     min_freq = mem1.read().strip()
        # with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", 'r') as mem1:
        #     max_freq = mem1.read().strip()
        # return (min_freq, max_freq, '')
        pass
    else:
        freq = subprocess.run('cpufreq-info -p', shell=True, stdout=subprocess.PIPE)
        if freq.returncode != 0:
            logging.warning('cpufreq-info gives error, cpufrequtils package installed?')
            return (0, 0, 0)
        else:
            return tuple(freq.stdout.decode('utf-8').strip().lower().split(' '))

def setMaxFreq(frequency, hardware, cores):
    if hardware != 0 :
        logging.info(f"Set max frequency to {int(frequency/1000)} MHz")
        for x in range(cores):
            logging.debug(f'Setting core {x} to {frequency} KHz')
            if subprocess.run(f'cpufreq-set -c {x} --max {frequency}', shell=True).returncode != 0:
                logging.warning('cpufreq-set gives error, cpufrequtils package installed?')
                break

def setGovernor(hardware, governor):
    if subprocess.run(f'cpufreq-set -g {governor}', shell=True).returncode != 0:
        logging.warning('cpufreq-set gives error, cpufrequtils package installed?')

def getCovernors(hardware):
    govs = subprocess.run('cpufreq-info -g', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if govs.returncode != 0:
        logging.warning('cpufreq-info gives error, cpufrequtils package installed?')
        return ()
    else:
        logging.debug(f'cpufreq-info governors: {govs.stdout.decode().strip()}')
        if govs.stdout is None:
            logging.warning('No covernors found!?')
            logging.debug(f'Govs: {govs.stdout.decode()}')
            return ()
        else:
            return tuple(govs.stdout.decode('utf-8').strip().lower().split(' '))

# if proces receives a kill signal or sigterm,
# raise an error and handle it in the finally statement for a proper exit
def signal_term_handler(self, args):
    raise KeyboardInterrupt()

def main():
    global version
    hardware = 0
    cur_temp = 0
    governor_high = 'ondemand'
    governor_low = 'powersave'
    cur_governor = 'performance'
    govs = ()
    relax_time, crit_temp, debug = getArguments()
    logging.debug(f'critic_temp: {crit_temp}, relaxtime: {relax_time}, debug: {debug}')
    cores = os.cpu_count()
    if cores is None:
        cores = 16
    hardware = hardwareCheck()
    logging.debug(f'Detected hardware/kernel type is {hardware}')
    if hardware == 0:
        logging.warning("Sorry, this hardware is not supported")
        sys.exit()
    freq = getMinMaxFrequencies(hardware)
    logging.debug(f'min max gov: {freq}')
    min_freq = int(freq[0])
    max_freq = int(freq[1])
    if freq[2] is not None:
        cur_governor = freq[2]
    govs = getCovernors(hardware)
    if governor_high not in govs:
        governor_high = 'performance'
    if governor_low not in govs:
        logging.warning('Wait, powersave mode not in governors list?')
        governor_low = 'userspace'
    # logging.debug(f'govs received: {govs}')
    signal.signal(signal.SIGINT, signal_term_handler)
    signal.signal(signal.SIGTERM, signal_term_handler)
    try:
        while True:
            # cur_temp = getTemp(hardware)
            cur_temp = get_cpu_temperature(hardware)
            logging.info(f'Current temp is {int(cur_temp/1000)}')
            if cur_temp is None:
                logging.warning('Error: Current temp is None?!')
                break
            if cur_temp > crit_temp:
                logging.warning("CPU temp too high")
                logging.info(f"Slowing down for {relax_time} seconds")
                setGovernor(hardware, governor_low)
                setMaxFreq(min_freq, hardware, cores)
                time.sleep(relax_time)
            else:
                setGovernor(hardware, governor_high)
                setMaxFreq(max_freq, hardware, cores)
            time.sleep(3)
    except KeyboardInterrupt:
        logging.warning('Terminating')
    finally:
        logging.warning('Setting max cpu and governor back to normal.')
        setGovernor(hardware, cur_governor)
        setMaxFreq(max_freq, hardware, cores)

if __name__ == '__main__':
	main()
