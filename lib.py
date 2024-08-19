from abc import ABC, abstractmethod
import os
import pynvml
import traceback
from typing import Optional
import subprocess
import xmltodict


def is_root():
    ret = os.geteuid() == 0
    return ret


# TODO: control CPU temperature under 65 celsius

TARGET_TEMP = 65
MAX_POWER_LIMIT_RATIO = 0.8

NVIDIA_SMI = "nvidia-smi"
ENCODING = "utf-8"
EXEC_TIMEOUT = 5


class AbstractStatSustainer(ABC):
    hardware_name = "Hardware"

    def __init__(self, run_forever: bool, target_temp=TARGET_TEMP):
        self.run_forever = run_forever
        self.target_temp = target_temp

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


class CPUStatSustainer(AbstractStatSustainer):
    hardware_name = "CPU"


class NVIDIAGPUStatSustainer(AbstractStatSustainer):
    hardware_name = "NVIDIA GPU"

    def __init__(
        self, target_temp=TARGET_TEMP, max_power_limit_ratio=MAX_POWER_LIMIT_RATIO
    ):
        super().__init__(run_forever=False, target_temp=target_temp)
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
        info, power_info, temp_info = self.get_current_stats(device_index)
        power_limit_set = power_info == self.get_target_power_limit(device_index)
        temp_limit_set = temp_info == TARGET_TEMP
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        persistent_mode = pynvml.nvmlDeviceGetPersistenceMode(handle)
        persistent_mode_set = persistent_mode == 1

        return power_limit_set and temp_limit_set and persistent_mode_set


class NVSMIGPUStatSustainer(NVIDIAGPUStatSustainer):
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


class ROCMSMIGPUStatSustainer(AbstractStatSustainer):
    hardware_name = "AMD GPU"


class HardwareStatSustainer:
    ...
