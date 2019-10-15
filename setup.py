"""Setup script for the Flockwave connections package."""

from glob import glob
from os.path import basename, splitext
from setuptools import setup, find_packages

requires = ["blinker>=1.4", "enum-compat>=0.0.2", "future>=0.17.1"]

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
    extras_require={},
    test_suite="test",
)
