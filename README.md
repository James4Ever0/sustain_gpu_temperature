<h1 align="center">Sustainer</h1>

<h2 align="center"><i>You don't have to do this.</i></h2>

<img align="center" src="https://github.com/james4ever0/sustain_gpu_temperature/blob/master/assets/repair_gpu.jpg?raw=true" alt="Need an engineer license?">

<p align="center">
<a href="https://github.com/james4ever0/sustainer/blob/master/LICENSE"><img alt="License: WTFPL" src="https://img.shields.io/badge/license-WTFPL-green.svg?style=flat"></a>
<a href="https://pypi.org/project/sustainer/"><img alt="PyPI" src="https://img.shields.io/pypi/v/sustainer"></a>
<a href="https://pepy.tech/project/sustainer"><img alt="Downloads" src="https://static.pepy.tech/badge/sustainer"></a>
<a href="https://github.com/james4ever0/sustain_gpu_temperature"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
</p>

Keep GPU and CPU temperatures within given limit.

With it you no longer have to worry about hardware heating up when running long time tasks, especially for your cheap **GTX1660**, P106 and P104 GPU cards.

## Demo

You can use the command line tool `sustainer`:

```bash
sustainer # default target is 'all', so both cpu and gpu stats will be sustained
python3 -m sustainer # alternative syntax

# to specify only cpu or gpu as target
sustainer --target cpu 
sustainer --target gpu  

# changing default configuration:
env TARGET_TEMP=60 sustainer # default: 65
env MAX_POWER_LIMIT_RATIO=0.7 sustainer # default: 0.8
env MAX_FREQ_RATIO=0.7 sustainer # default: 0.8
```

Optionally run with a process manager such as [pm2](https://pm2.keymetrics.io/) to persist as daemon:

```bash
pm2 start -n sustainer_daemon sustainer
pm2 save
```

If you want to call it with code, check out the [test files](./tests/).

## Install

First, install from PyPI:

```bash
pip install sustainer
```

Then, install the following binaries:

```bash
# Ubuntu
sudo apt install -y cpufrequtils lm-sensors

# Debian
sudo apt install -y linux-cpupower lm-sensors
```

For NVIDIA GPU, you need to install related drivers and make sure `nvidia-smi` is in PATH.

For AMD GPU, install ROCm drivers and make sure `rocm-smi` is in PATH.

## Supported hardware

CPU: Intel, AMD, ARM

GPU: NVIDIA, AMD

## Supported platform

Linux only currently.

## Stargazers

<picture>
  <source
    media="(prefers-color-scheme: dark)"
    srcset="
      https://api.star-history.com/svg?repos=james4ever0/sustain_gpu_temperature&type=Date&theme=dark
    "
  />
  <source
    media="(prefers-color-scheme: light)"
    srcset="
      https://api.star-history.com/svg?repos=james4ever0/sustain_gpu_temperature&type=Date
    "
  />
  <img
    alt="Star History Chart"
    src="https://api.star-history.com/svg?repos=james4ever0/sustain_gpu_temperature&type=Date"
  />
</picture>
