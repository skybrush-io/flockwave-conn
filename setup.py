"""Setup script for the Flockwave connections package."""

from glob import glob
from os.path import basename, splitext
from setuptools import setup, find_packages

requires = ["attr>=19.3.0", "blinker>=1.4", "trio>=0.12.1", "trio_util>=0.1.0"]

__version__ = None
exec(open("src/flockwave/connections/version.py").read())

setup(
    name="flockwave-conn",
    version=__version__,
    author=u"Tam\u00e1s Nepusz",
    author_email="tamas@collmot.com",
    packages=find_packages("src"),
    package_dir={"": "src"},
    py_modules=[splitext(basename(path))[0] for path in glob("src/*.py")],
    include_package_data=True,
    python_requires=">=3.7",
    install_requires=requires,
    extras_require={
        "midi": ["mido>=1.2.9", "python-rtmidi>=1.3.1"],
        "serial": ["pyserial>=3.4"],
    },
    test_suite="test",
)
