from abc import ABC, abstractmethod
import os
import pynvml
import traceback
from typing import Optional, Union, Callable, List, Dict, Any
import subprocess
import xmltodict
import shutil
import functools

import sys, time
import logging, signal
import json
import threading


def is_root():
    ret = os.geteuid() == 0
    return ret


def repeat_task(func: Optional[Callable] = None, sleep_time: float = 10):
    while True:
        try:
            if func is not None:
                func()
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("[*] Exiting because of keyboard interruption")
            break
        except:
            traceback.print_exc()
            print("[-] Exception while running task")
            time.sleep(5)


def start_as_daemon_thread(func: Callable):
    thread = threading.Thread(target=func, daemon=True)
    thread.start()


def get_value_from_environ_with_fallback(name: str, fallback_value):
    ret = os.environ.get(name, fallback_value)
    ret = type(fallback_value)(ret)
    return ret


# for linux only.
# TODO: control CPU temperature under 65 celsius

TARGET_TEMP = get_value_from_environ_with_fallback("TARGET_TEMP", 65)
MAX_POWER_LIMIT_RATIO = get_value_from_environ_with_fallback(
    "MAX_POWER_LIMIT_RATIO", 0.8
)
MAX_FREQ_RATIO = get_value_from_environ_with_fallback("MAX_FREQ_RATIO", 0.8)

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

def retrieve_usable_sustainer_from_list(sustainer_list:List["AbstractBaseStatSustainer.__class__"]):
    namelist = []
    for it in sustainer_list:
        name = it.__name__
        namelist.append(name)
        try:
            instance = it()
            if instance.test():
                # test passed
                print('[+] Using sustainer:', name)
                return instance
            else:
                print('[-] Removing unusable sustainer:', name)
                del instance
        except:
            traceback.print_exc()
            print(f"[-] Failed to create an instance for '{name}'")
    raise Exception('[-] No usable sustainer found in:', *namelist)


class AbstractBaseStatSustainer(ABC):
    hardware_name = "Hardware"
    required_binaries: List[str] = []
    run_forever: bool

    def __init__(self, target_temp=TARGET_TEMP):
        assert is_root(), "You must be root to execute this script"
        self.target_temp = target_temp
        self.verify_binary_requirements()

    def verify_binary_requirements(self):
        for it in self.required_binaries:
            assert check_binary_in_path(it), f"Binary '{it}' not found in path"

    @abstractmethod
    def main(self):
        ...

    @abstractmethod
    def test(self) -> bool:
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
    def test(self):
        ret = False
        try:
            self.mainloop()
            ret = True
        except:
            traceback.print_exc()
            print(f"[-] Test failed for running '{self.__name__}'")
        return ret

    def main(self):
        while True:
            try:
                self.mainloop()
                if not self.run_forever:
                    break
            except:
                traceback.print_exc()
                print("[-] Failed to run current loop")

    @abstractmethod
    def get_device_indices(self) -> List[int]:
        ...

    @abstractmethod
    def verify_stats(self, device_id: int) -> bool:
        ...

    @abstractmethod
    def set_stats(self, device_id: int):
        ...


class CPUBaseStatSustainer(AbstractBaseStatSustainer):
    hardware_name = "CPU"
    run_forever = True


class CPUFreqUtilStatSustainer(CPUBaseStatSustainer):
    required_binaries = ["sensors", "cpufreq-info", "cpufreq-set"]

    def __init__(self, relax_time: Optional[int] = None, max_freq_ratio=MAX_FREQ_RATIO):
        super().__init__()
        self.logger_init()
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
    def check_prefix_in_strlist(strlist: List[str], prefix: str):
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
        readings: Dict[str, dict], prefix: str
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
            hwfreq = subprocess.run(
                "cpufreq-info -l", shell=True, stdout=subprocess.PIPE
            )
            assert hwfreq.returncode == 0, "failed to get hardware frequency limit"
            if freq.returncode != 0:
                logging.warning(
                    "cpufreq-info gives error, cpufrequtils package installed?"
                )
                return (0, 0, 0)
            else:
                return tuple(
                    [
                        *hwfreq.stdout.decode("utf-8").strip().split(" "),
                        freq.stdout.decode("utf-8").strip().lower().split(" ")[-1],
                    ]
                )

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

    def set_signal_handler(self):
        try:
            signal.signal(signal.SIGINT, self.signal_term_handler)
            signal.signal(signal.SIGTERM, self.signal_term_handler)
        except ValueError:
            print("[-] Failed to set signal handler for CPUStatSustainer")

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
        max_freq_limit = int(max_freq * self.max_freq_ratio)
        init_freq = int((max_freq + min_freq) / 2)
        freq_step = 300 * 1000
        if freq[2] is not None:
            cur_governor = freq[2]
        govs = self.getCovernors(hardware)
        if governor_high not in govs:
            governor_high = "performance"
        if governor_low not in govs:
            logging.warning("Wait, powersave mode not in governors list?")
            governor_low = "userspace"
        # logging.debug(f'govs received: {govs}')
        self.set_signal_handler()
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


class CPUPowerStatSustainer(CPUFreqUtilStatSustainer):
    required_binaries = ['sensors', 'cpuinfo', 'cpufreq']

class NVIDIABaseGPUStatSustainer(AbstractBaseStatSustainer):
    hardware_name = "NVIDIA GPU"

class NVIDIAGPUStatSustainer(NVIDIABaseGPUStatSustainer, AbstractStatSustainer):
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
    def prepare_nvidia_smi_command(suffix: List[str], device_id: Optional[int] = None):
        cmdlist = [NVIDIA_SMI]
        if device_id is not None:
            cmdlist.extend(["-i", str(device_id)])
        cmdlist.extend(suffix)
        print("[*] Prepared NVIDIA-SMI command:", cmdlist)
        return cmdlist

    def execute_nvidia_smi_command(
        self, suffix: List[str], device_id: Optional[int] = None, timeout=EXEC_TIMEOUT
    ):
        cmdlist = self.prepare_nvidia_smi_command(suffix, device_id)
        subprocess.run(cmdlist, timeout=timeout)

    @staticmethod
    def parse_number(power_limit_string: str):
        try:
            ret = float(power_limit_string.split(" ")[0])
            ret = int(ret)
        except ValueError:
            print(f"[-] Failed to convert '{power_limit_string}' as number, falling back to nan")
            ret = float('nan')
        return ret

    def get_gpu_info_by_id(self, device_id:int) -> dict:
        data = self.get_current_stats()
        ret = data["gpu"][device_id]
        return ret

    def get_gpu_power_readings_by_id(self, device_id:int):
        data = self.get_gpu_info_by_id(device_id)
        ret = data.get('power_readings', data.get('gpu_power_readings', None))
        assert ret is not None, '[-] Failed to get GPU power readings'
        return ret

    def get_default_power_limit(self, device_id: int):
        ret = self.parse_number(
            self.get_gpu_power_readings_by_id(device_id)["default_power_limit"]
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
        data = self.get_gpu_info_by_id(device_id)
        power_readings = self.get_gpu_power_readings_by_id(device_id)
        power_limit = self.parse_number(
            power_readings.get("current_power_limit", power_readings.get('power_limit', None)
        ))
        temp_limit = self.parse_number(
            data["temperature"]["gpu_target_temperature"]
        )
        persistent_mode = data["persistence_mode"]

        power_limit_set = power_limit == self.get_target_power_limit(device_id)
        temp_limit_set = temp_limit == TARGET_TEMP
        persistent_mode_set = persistent_mode == "Enabled"

        return power_limit_set and temp_limit_set and persistent_mode_set

class NVIDIALegacyGPUStatSustainer(NVSMIGPUStatSustainer):
    run_forever = True
    def main(self):
        ...

class ROCMSMIGPUStatSustainer(AbstractBaseStatSustainer):
    hardware_name = "AMD GPU"
    run_forever = True
    required_binaries = ["rocm-smi"]

    @staticmethod
    def generate_rocm_cmdline(
        suffixs: List[str], device_id: Optional[int], export_json: bool
    ):
        cmdline = ["rocm-smi"]
        if device_id is not None:
            cmdline += ["-d", str(device_id)]
        cmdline += suffixs
        if export_json:
            cmdline += ["--json"]
        # print('[*] Generated cmdline:', cmdline)
        return cmdline

    def execute_rocm_cmdline(
        self,
        suffixs: List[str],
        device_id: Optional[int] = None,
        export_json=True,
        timeout=EXEC_TIMEOUT,
    ) -> Any:
        cmdline = self.generate_rocm_cmdline(
            suffixs, device_id=device_id, export_json=export_json
        )
        output = subprocess.check_output(cmdline, timeout=timeout, encoding=ENCODING)
        if export_json:
            output = json.loads(output)
        # print('[*] Output:')
        # print(output)
        return output

    def get_gpu_sclk_min_max_levels(self, device_id: int):
        data: dict = self.execute_rocm_cmdline(["-s"], device_id)
        level_data = self.get_first_value_from_dict(data)
        levels = [int(it) for it in level_data.keys()]
        min_level, max_level = min(levels), max(levels)
        return min_level, max_level

    def get_gpu_current_sclk_level(self, device_id: int):
        data: dict = self.execute_rocm_cmdline(["-c"], device_id=device_id)
        level_data = self.get_first_value_from_dict(data)
        ret = int(level_data["sclk clock level:"])
        return ret

    def get_device_indices(self):
        data: dict = self.execute_rocm_cmdline(["--showtopo"])
        # count for keys
        device_count = len(data.keys())
        ret = list(range(device_count))
        return ret

    @staticmethod
    def get_first_value_from_dict(data: dict):
        ret = list(data.values())[0]
        return ret

    def set_gpu_sclk_level(self, device_id: int, sclk_level: int):
        self.execute_rocm_cmdline(
            ["--setsclk", str(sclk_level)], device_id=device_id, export_json=False
        )

    def set_gpu_as_manual_perf_level(self, device_id: int):
        self.execute_rocm_cmdline(
            ["--setperflevel", "manual"], device_id=device_id, export_json=False
        )

    def get_gpu_temperature(self, device_id: int):
        data: dict = self.execute_rocm_cmdline(["-t"], device_id=device_id)
        temp_data = self.get_first_value_from_dict(data)
        ret = 0
        for name, value in temp_data.items():
            try:
                value = float(value)
                ret = max(value, ret)
            except ValueError:
                print(f'[-] Failed to convert value "{value}" ({name}) to float')
        return ret

    def mainloop(self):
        for it in self.get_device_indices():
            print("[*] Processing GPU #" + str(it))
            self.set_gpu_as_manual_perf_level(it)
            gpu_temp = self.get_gpu_temperature(it)
            current_sclk_level = self.get_gpu_current_sclk_level(it)
            print("[*] Current SCLK level:", current_sclk_level)
            min_sclk_level, max_sclk_level = self.get_gpu_sclk_min_max_levels(it)
            print("[*] GPU temperature:", gpu_temp)
            if gpu_temp > self.target_temp:
                print("[*] Temperature too high. Lowering SCLK level")
                new_sclk_level = current_sclk_level - 1
                new_sclk_level = max(min_sclk_level, new_sclk_level)
            else:
                print("[*] Temperature within limit. Rising SCLK level")
                new_sclk_level = current_sclk_level + 1
                new_sclk_level = min(max_sclk_level, new_sclk_level)
            print("[*] New SCLK level:", new_sclk_level)
            self.set_gpu_sclk_level(it, new_sclk_level)

    def main(self):
        while True:
            self.mainloop()
            time.sleep(5)


def get_usable_cpu_sustainer():
    ret = retrieve_usable_sustainer_from_list([CPUFreqUtilStatSustainer, CPUPowerStatSustainer])
    return ret


def get_usable_nvidia_gpu_sustainer():
    ret = retrieve_usable_sustainer_from_list([NVSMIGPUStatSustainer, NVMLGPUStatSustainer, NVIDIALegacyGPUStatSustainer])
    return ret

def get_usable_amd_gpu_sustainer():
    ret = retrieve_usable_sustainer_from_list([ROCMSMIGPUStatSustainer])
    return ret


class HardwareStatSustainer:
    def __init__(self, cpu=True, gpu=True):
        self.sustainers: List[AbstractBaseStatSustainer] = []
        if cpu:
            self.sustainers.append(get_usable_cpu_sustainer())
        if gpu:
            self.add_gpu_sustainers()

    def add_gpu_sustainers(self):
        # must have cpu, so we check for nvidia gpu and amd gpu
        if self.has_nvidia_gpu():
            self.sustainers.append(get_usable_nvidia_gpu_sustainer())
        if self.has_amd_gpu():
            self.sustainers.append(get_usable_amd_gpu_sustainer())

    @staticmethod
    def has_nvidia_gpu() -> bool:
        return check_binary_in_path(NVIDIA_SMI)

    @staticmethod
    def has_amd_gpu() -> bool:
        return check_binary_in_path(ROCM_SMI)

    def main(self):
        for it in self.sustainers:
            func = it.main
            if not it.run_forever:
                func = functools.partial(repeat_task, func)
            start_as_daemon_thread(func)
        repeat_task()
