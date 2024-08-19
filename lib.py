from abc import ABC, abstractmethod
import pynvml

# TODO: control CPU temperature under 65 celsius


class CPUStatSustainer(ABC):
    ...


class GPUStatSustainer(ABC):
    ...


class HardwareStatSustainer(ABC):
    ...


class NVMLGPUStatSustainer(GPUStatSustainer):
    def __init__(self):
        pynvml.nvmlInit()


class NVSMIGPUStatSustainer(GPUStatSustainer):
    ...


class ROCMSMIGPUStatSustainer(GPUStatSustainer):
    ...
