import argparse
from .lib import HardwareStatSustainer
import sys
import traceback

def parse_args():
    # Create the parser
    parser = argparse.ArgumentParser(
        description="Keep GPU and CPU temperatures within given limit.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Add arguments
    parser.add_argument(
        "-t",
        "--target",
        type=str,
        default="all",
        choices=["all", "cpu", "gpu"],
        help="""Specify the hardware target to sustain stats.""",
    )

    # Provide additional help information
    parser.epilog = """
environment variables:
    TARGET_TEMP (default: 65)
        target temperature to sustain at
    MAX_POWER_LIMIT_RATIO (default: 0.8)
        max power consumption compared to hardware enforced limit
    MAX_FREQ_RATIO (default: 0.8)
        max frequency compared to hardware enforced limit
"""

    # Parse the arguments
    args = parser.parse_args()
    return args


def call_sustainer(target: str):
    kwargs = {}
    if target == "cpu":
        kwargs["gpu"] = False
    elif target == "gpu":
        kwargs["cpu"] = False
    HardwareStatSustainer(**kwargs).main()

def github_info_excepthook(exctype, value, tb):
    info = """
Encountered issues? Stay in touch with us!

Submit a new issue: https://github.com/james4ever0/sustain_gpu_temperature/issues/new

You are more than welcomed to submit a pull request instead!
"""
    traceback_details = '\n'.join(traceback.extract_tb(tb).format())

    error_msg = "An exception has been raised outside of a try/except!!!\n" \
                f"Type: {exctype}\n" \
                f"Value: {value}\n" \
                f"Traceback:\n{traceback_details}{info}"
    print(error_msg)    

def set_excepthook():
    sys.excepthook = github_info_excepthook

def main():
    set_excepthook()
    cli_args = parse_args()
    target = cli_args.target
    call_sustainer(target)


if __name__ == "__main__":
    main()
