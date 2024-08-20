from abc import ABC, abstractmethod
import os
import pynvml
import traceback
from typing import Optional, Union,Callable
import subprocess
import xmltodict
import shutil

import sys, time
import logging, signal
import json
import threading


def is_root():
    ret = os.geteuid() == 0
    return ret

def start_as_daemon_thread(func:Callable):
    thread = threading.Thread(target=func, daemon=True)
    thread.start()

# for linux only.
# TODO: control CPU temperature under 65 celsius

TARGET_TEMP = 65
MAX_POWER_LIMIT_RATIO = 0.8
MAX_FREQ_RATIO = 0.8

NVIDIA_SMI = "nvidia-smi"
ENCODING = "utf-8"
EXEC_TIMEOUT = 5

ROCM_SMI = "rocm-smi"

CPU_TEMP_SENSOR_PREFIXS = ["coretemp-", "cpu_thermal", "k10temp"]


def check_binary_in_path(binary_name: str):
    ret = shutil.which(binary_name) != None
    if ret:
        print(f"[+] Binary '{binary_name}' detected")
    return ret


class AbstractBaseStatSustainer(ABC):
    hardware_name = "Hardware"
    required_binaries: list[str] = []
    run_forever: bool

    def __init__(self, target_temp=TARGET_TEMP):
        self.target_temp = target_temp
        self.verify_binary_requirements()

    def verify_binary_requirements(self):
        for it in self.required_binaries:
            assert check_binary_in_path(it), f"Binary '{it}' not found in path"

    @abstractmethod
    def main(self):
        ...


class AbstractStatSustainer(AbstractBaseStatSustainer):
    def mainloop(self):
        for index in self.get_device_indices():
            all_set = self.verify_stats(index)
            if all_set:
                print(
                    f"[*] {self.hardware_name} stat limits are already set correctly."
                )
            else:
                self.set_stats(index)
                print(f"[+] {self.hardware_name} stat limits have been adjusted.")
                assert self.verify_stats(
                    index
                ), f"[-] {self.hardware_name} stat limits verification failed"

    def main(self):
        assert is_root(), "You must be root to execute this script"
        while True:
            try:
                self.mainloop()
                if not self.run_forever:
                    break
            except:
                traceback.print_exc()
                print("[-] Failed to run current loop")

    @abstractmethod
    def get_device_indices(self) -> list[int]:
        ...

    @abstractmethod
    def verify_stats(self, device_id: int) -> bool:
        ...

    @abstractmethod
    def set_stats(self, device_id: int):
        ...


class CPUStatSustainer(AbstractBaseStatSustainer):
    hardware_name = "CPU"
    run_forever = True
    required_binaries = ["sensors", "cpufreq-info", "cpufreq-set"]

    def __init__(self, relax_time: Optional[int] = None, max_freq_ratio=MAX_FREQ_RATIO):
        self.logger_init()
        super().__init__()
        self.max_freq_ratio = max_freq_ratio
        self.relax_time, self.crit_temp = self.getArguments(
            relax_time, self.target_temp
        )

    @staticmethod
    def logger_init():
        logging.basicConfig(
            level=logging.INFO,
            # level=logging.DEBUG,
            format="%(asctime)s [%(levelname)8s] %(message)s",
            handlers=[
                logging.FileHandler("/var/log/cpu_throttle.log"),
                logging.StreamHandler(sys.stdout),
            ],
        )

    @staticmethod
    def get_temperature_readings():
        cmdlist = ["sensors", "-j"]
        output = subprocess.check_output(cmdlist, encoding="utf-8")
        ret = json.loads(output)
        return ret

    @staticmethod
    def check_prefix_in_strlist(strlist: list[str], prefix: str):
        ret = False
        for it in strlist:
            if it.startswith(prefix):
                ret = True
                break
        return ret

    def detect_platform_from_readings(self, readings: dict):
        reading_keys = list(readings.keys())
        ret = -1
        for index, elem in enumerate(CPU_TEMP_SENSOR_PREFIXS):
            if self.check_prefix_in_strlist(reading_keys, elem):
                ret = index
                break
        return ret

    @staticmethod
    def filter_by_prefix_and_calculate_max_value_from_readings(
        readings: dict[str, dict], prefix: str
    ):
        ret = 0
        for adaptor_name, sensor in readings.items():
            if adaptor_name.startswith(prefix):
                for _, sensor_value in sensor.items():
                    if type(sensor_value) is dict:
                        for (
                            sensor_value_key,
                            sensor_value_reading,
                        ) in sensor_value.items():
                            if sensor_value_key.endswith("_input"):
                                ret = max(ret, sensor_value_reading)
        return ret

    def get_cpu_temperature(self, hardware: int):
        readings = self.get_temperature_readings()
        ret = None
        platform_id = self.detect_platform_from_readings(readings)
        ret = 0
        if platform_id != -1:
            prefix = CPU_TEMP_SENSOR_PREFIXS[platform_id]
            ret = (
                self.filter_by_prefix_and_calculate_max_value_from_readings(
                    readings, prefix
                )
                * 1000
            )
        if int(ret) == 0:
            ret = self.getTemp(hardware)
        return ret

    @staticmethod
    def getArguments(time: Optional[int], crit_temp: Optional[int]):
        if time is None:
            relaxtime = 1  # time in seconds
        else:
            relaxtime = int(time)
        if crit_temp is None:
            crit_temp = 64000  # temp in mili celcius degree
        else:
            crit_temp = int(crit_temp) * 1000
        return relaxtime, crit_temp

    # determine hardware and kernel types
    @staticmethod
    def hardwareCheck():
        # does this work: $ echo "performance" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
        if (
            os.path.exists(
                "/sys/devices/LNXSYSTM:00/LNXTHERM:00/LNXTHERM:01/thermal_zone/temp"
            )
            == True
        ):
            return 4
        elif (
            os.path.exists("/sys/bus/acpi/devices/LNXTHERM:00/thermal_zone/temp")
            == True
        ):
            return 5  # intel
        elif os.path.exists("/sys/class/hwmon/hwmon0") == True:
            return 6  # amd
        elif os.path.exists("/sys/class/thermal/thermal_zone3/") == True:
            return 7  # intel
        elif os.path.exists("/proc/acpi/thermal_zone/THM0/temperature") == True:
            return 1
        elif os.path.exists("/proc/acpi/thermal_zone/THRM/temperature") == True:
            return 2
        elif os.path.exists("/proc/acpi/thermal_zone/THR1/temperature") == True:
            return 3
        else:
            return 0

    # depending on the kernel and hardware config, read the temperature
    @staticmethod
    def getTemp(hardware: int):
        temp = 0
        if hardware == 6:
            # logging.debug('reading temp..')
            with open("/sys/class/hwmon/hwmon0/temp1_input", "r") as mem1:
                temp = mem1.read().strip()
        elif hardware == 1:
            temp = (
                open("/proc/acpi/thermal_zone/THM0/temperature")
                .read()
                .strip()
                .lstrip("temperature :")
                .rstrip(" C")
            )
        elif hardware == 2:
            temp = (
                open("/proc/acpi/thermal_zone/THRM/temperature")
                .read()
                .strip()
                .lstrip("temperature :")
                .rstrip(" C")
            )
        elif hardware == 3:
            temp = (
                open("/proc/acpi/thermal_zone/THR1/temperature")
                .read()
                .strip()
                .lstrip("temperature :")
                .rstrip(" C")
            )
        elif hardware == 4:
            temp = (
                open(
                    "/sys/devices/LNXSYSTM:00/LNXTHERM:00/LNXTHERM:01/thermal_zone/temp"
                )
                .read()
                .strip()
                .rstrip("000")
            )
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

    @staticmethod
    def getMinMaxFrequencies(hardware: int):
        if hardware == 0:
            # with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq", 'r') as mem1:
            #     min_freq = mem1.read().strip()
            # with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", 'r') as mem1:
            #     max_freq = mem1.read().strip()
            # return (min_freq, max_freq, '')
            raise Exception("Unable to get CPU frequency for unknown hardware")
        else:
            freq = subprocess.run("cpufreq-info -p", shell=True, stdout=subprocess.PIPE)
            hwfreq = subprocess.run("cpufreq-info -l", shell=True, stdout=subprocess.PIPE)
            assert hwfreq.returncode == 0, 'failed to get hardware frequency limit'
            if freq.returncode != 0:
                logging.warning(
                    "cpufreq-info gives error, cpufrequtils package installed?"
                )
                return (0, 0, 0)
            else:
                return tuple([*hwfreq.stdout.decode('utf-8').strip().split(" "), freq.stdout.decode("utf-8").strip().lower().split(" ")[-1]])

    @staticmethod
    def setMaxFreq(frequency: int, hardware: int, cores: int):
        if hardware != 0:
            logging.info(f"Set max frequency to {int(frequency/1000)} MHz")
            for x in range(cores):
                logging.debug(f"Setting core {x} to {frequency} KHz")
                if (
                    subprocess.run(
                        f"cpufreq-set -c {x} --max {frequency}", shell=True
                    ).returncode
                    != 0
                ):
                    logging.warning(
                        "cpufreq-set gives error, cpufrequtils package installed?"
                    )
                    break

    @staticmethod
    def setGovernor(hardware: int, governor: Union[str, int]):
        if subprocess.run(f"cpufreq-set -g {governor}", shell=True).returncode != 0:
            logging.warning("cpufreq-set gives error, cpufrequtils package installed?")

    @staticmethod
    def getCovernors(hardware: int):
        govs = subprocess.run(
            "cpufreq-info -g",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if govs.returncode != 0:
            logging.warning("cpufreq-info gives error, cpufrequtils package installed?")
            return ()
        else:
            logging.debug(f"cpufreq-info governors: {govs.stdout.decode().strip()}")
            if govs.stdout is None:
                logging.warning("No covernors found!?")
                logging.debug(f"Govs: {govs.stdout.decode()}")
                return ()
            else:
                return tuple(govs.stdout.decode("utf-8").strip().lower().split(" "))

    # if proces receives a kill signal or sigterm,
    # raise an error and handle it in the finally statement for a proper exit
    @staticmethod
    def signal_term_handler(self, args):  # type:ignore
        raise KeyboardInterrupt()

    def main(self):
        # global version
        hardware = 0
        cur_temp = 0
        governor_high = "ondemand"
        governor_low = "powersave"
        cur_governor = "performance"
        govs = ()
        relax_time, crit_temp = self.relax_time, self.crit_temp
        logging.debug(f"critic_temp: {crit_temp}, relaxtime: {relax_time}")
        cores = os.cpu_count()
        if cores is None:
            cores = 16
        hardware = self.hardwareCheck()
        logging.debug(f"Detected hardware/kernel type is {hardware}")
        if hardware == 0:
            logging.warning("Sorry, this hardware is not supported")
            sys.exit()
        freq = self.getMinMaxFrequencies(hardware)
        logging.debug(f"min max gov: {freq}")
        min_freq = int(freq[0])
        max_freq = int(freq[1])
        max_freq_limit = int(max_freq*self.max_freq_ratio)
        init_freq = int((max_freq + min_freq)/2)
        freq_step = 300*1000
        if freq[2] is not None:
            cur_governor = freq[2]
        govs = self.getCovernors(hardware)
        if governor_high not in govs:
            governor_high = "performance"
        if governor_low not in govs:
            logging.warning("Wait, powersave mode not in governors list?")
            governor_low = "userspace"
        # logging.debug(f'govs received: {govs}')
        signal.signal(signal.SIGINT, self.signal_term_handler)
        signal.signal(signal.SIGTERM, self.signal_term_handler)
        try:
            while True:
                # cur_temp = getTemp(hardware)
                cur_temp = self.get_cpu_temperature(hardware)
                logging.info(f"Current temp is {int(cur_temp/1000)}")
                if cur_temp is None:
                    logging.warning("Error: Current temp is None?!")
                    break
                if cur_temp > crit_temp:
                    logging.warning("CPU temp too high")
                    logging.info(f"Slowing down for {relax_time} seconds")
                    init_freq -= freq_step
                    init_freq = max(init_freq, min_freq)
                    self.setGovernor(hardware, governor_low)
                    self.setMaxFreq(init_freq, hardware, cores)
                    # self.setMaxFreq(min_freq, hardware, cores)
                    time.sleep(relax_time)
                else:
                    init_freq += freq_step
                    init_freq = min(init_freq, max_freq_limit) 
                    self.setGovernor(hardware, governor_high)
                    self.setMaxFreq(init_freq, hardware, cores)
                time.sleep(1)
        except KeyboardInterrupt:
            logging.warning("Terminating")
        finally:
            logging.warning("Setting max cpu and governor back to normal.")
            self.setGovernor(hardware, cur_governor)
            self.setMaxFreq(max_freq, hardware, cores)


class NVIDIAGPUStatSustainer(AbstractStatSustainer):
    hardware_name = "NVIDIA GPU"
    run_forever = False

    def __init__(
        self, target_temp=TARGET_TEMP, max_power_limit_ratio=MAX_POWER_LIMIT_RATIO
    ):
        super().__init__(target_temp=target_temp)
        self.max_power_limit_ratio = max_power_limit_ratio


class NVMLGPUStatSustainer(NVIDIAGPUStatSustainer):
    def main(self):
        pynvml.nvmlInit()
        super().main()
        pynvml.nvmlShutdown()

    @staticmethod
    def get_device_indices():
        num_gpus = pynvml.nvmlDeviceGetCount()
        ret = list(range(num_gpus))
        return ret

    @staticmethod
    def get_current_stats(device_index: int):
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)

        info = pynvml.nvmlDeviceGetUtilizationRates(handle)
        power_info = pynvml.nvmlDeviceGetEnforcedPowerLimit(handle)
        temp_info = pynvml.nvmlDeviceGetTemperatureThreshold(
            handle, pynvml.NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR
        )
        return info, power_info, temp_info

    @staticmethod
    def get_target_power_limit(device_index: int):
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        default_power_limit = pynvml.nvmlDeviceGetPowerManagementDefaultLimit(handle)
        ret = int(default_power_limit * MAX_POWER_LIMIT_RATIO)
        return ret

    def set_stats(self, device_index: int):
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)

        new_power_limit = self.get_target_power_limit(device_index)

        pynvml.nvmlDeviceSetPowerManagementLimit(handle, new_power_limit)
        pynvml.nvmlDeviceSetTemperatureThreshold(
            handle, pynvml.NVML_TEMPERATURE_THRESHOLD_ACOUSTIC_CURR, TARGET_TEMP
        )

        pynvml.nvmlDeviceSetPersistenceMode(handle, 1)

    def verify_stats(self, device_index: int):
        _, power_info, temp_info = self.get_current_stats(device_index)
        power_limit_set = power_info == self.get_target_power_limit(device_index)
        temp_limit_set = temp_info == TARGET_TEMP
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        persistent_mode = pynvml.nvmlDeviceGetPersistenceMode(handle)
        persistent_mode_set = persistent_mode == 1

        return power_limit_set and temp_limit_set and persistent_mode_set


class NVSMIGPUStatSustainer(NVIDIAGPUStatSustainer):
    required_binaries = [NVIDIA_SMI]

    def get_device_indices(self):
        data = self.get_current_stats()
        num_gpus = int(data["attached_gpus"])
        ret = list(range(num_gpus))
        return ret

    def get_current_stats(self):
        cmdlist = self.prepare_nvidia_smi_command(["-x", "-q"])
        output = subprocess.check_output(cmdlist).decode(ENCODING)
        data = xmltodict.parse(output)
        data = data["nvidia_smi_log"]
        if type(data["gpu"]) != list:
            data["gpu"] = [data["gpu"]]

        return data

    @staticmethod
    def prepare_nvidia_smi_command(suffix: list[str], device_id: Optional[int] = None):
        cmdlist = [NVIDIA_SMI]
        if device_id is not None:
            cmdlist.extend(["-i", str(device_id)])
        cmdlist.extend(suffix)
        print("[*] Prepared NVIDIA-SMI command:", cmdlist)
        return cmdlist

    def execute_nvidia_smi_command(
        self, suffix: list[str], device_id: Optional[int] = None, timeout=EXEC_TIMEOUT
    ):
        cmdlist = self.prepare_nvidia_smi_command(suffix, device_id)
        subprocess.run(cmdlist, timeout=timeout)

    @staticmethod
    def parse_number(power_limit_string: str):
        ret = float(power_limit_string.split(" ")[0])
        ret = int(ret)
        return ret

    def get_default_power_limit(self, device_id: int):
        data = self.get_current_stats()
        ret = self.parse_number(
            data["gpu"][device_id]["gpu_power_readings"]["default_power_limit"]
        )
        return ret

    def get_target_power_limit(self, device_id: int):
        default_power_limit = self.get_default_power_limit(device_id)
        ret = int(MAX_POWER_LIMIT_RATIO * default_power_limit)
        return ret

    def set_stats(self, device_id: int):
        power_limit = self.get_target_power_limit(device_id)
        suffix_list = [
            ["-pl", str(power_limit)],
            ["-gtt", str(TARGET_TEMP)],
            ["-pm", "1"],
        ]
        for it in suffix_list:
            self.execute_nvidia_smi_command(it, device_id=device_id)

    def verify_stats(self, device_id: int):
        data = self.get_current_stats()

        power_limit = self.parse_number(
            data["gpu"][device_id]["gpu_power_readings"]["current_power_limit"]
        )
        temp_limit = self.parse_number(
            data["gpu"][device_id]["temperature"]["gpu_target_temperature"]
        )
        persistent_mode = data["gpu"][device_id]["persistence_mode"]

        power_limit_set = power_limit == self.get_target_power_limit(device_id)
        temp_limit_set = temp_limit == TARGET_TEMP
        persistent_mode_set = persistent_mode == "Enabled"

        return power_limit_set and temp_limit_set and persistent_mode_set


class ROCMSMIGPUStatSustainer(AbstractBaseStatSustainer):
    hardware_name = "AMD GPU"
    run_forever = True
    required_binaries = ['rocm-smi']


class HardwareStatSustainer:
    def __init__(self):
        self.sustainers: list[AbstractBaseStatSustainer] = [CPUStatSustainer()]
        self.add_gpu_sustainers()

    def add_gpu_sustainers(self):
        # must have cpu, so we check for nvidia gpu and amd gpu
        if self.has_nvidia_gpu():
            self.sustainers.append(NVSMIGPUStatSustainer())
        if self.has_amd_gpu():
            self.sustainers.append(ROCMSMIGPUStatSustainer())

    @staticmethod
    def has_nvidia_gpu() -> bool:
        return check_binary_in_path(NVIDIA_SMI)

    @staticmethod
    def has_amd_gpu() -> bool:
        return check_binary_in_path(ROCM_SMI)

    @staticmethod
    def idle():
        while True:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                print("[*] Exiting because of keyboard interruption")
                break

    def main(self):
        for it in self.sustainers:
            start_as_daemon_thread(it)
        self.idle()
