import argparse
from .lib import HardwareStatSustainer


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


def main():
    cli_args = parse_args()
    target = cli_args.target
    call_sustainer(target)


if __name__ == "__main__":
    main()
