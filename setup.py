from setuptools import setup

setup(
    name="sustainer",
    version="0.0.5",
    packages=["sustainer"],
    description="Keep GPU and CPU temperatures within given limit.",
    url="https://github.com/james4ever0/sustain_gpu_temperature",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    license=open("LICENSE").read(),
    install_requires=open("requirements.txt").read().strip().splitlines(),
    entry_points="""
        [console_scripts]
        sustainer=sustainer.cli:main
    """,
)
