# pid control reference: https://pypi.org/project/PID-Py/
# https://github.com/jluo1875/CPU-Temperature-Throttler
from lib import CPUStatSustainer


def test():
    CPUStatSustainer().main()


if __name__ == "__main__":
    test()
