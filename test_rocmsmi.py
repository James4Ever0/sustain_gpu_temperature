from lib import ROCMSMIGPUStatSustainer

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

def test():
    ROCMSMIGPUStatSustainer().main()

if __name__ == "__main__":
    test()
    # main()
