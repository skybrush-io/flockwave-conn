"""Setup script for the Flockwave connections package."""

from setuptools import setup, find_packages

requires = [
    "blinker>=1.4",
    "enum-compat>=0.0.2",
    "future>=0.17.1"
]

__version__ = None
exec(open("flockwave/connections/version.py").read())

setup(
    name="flockwave-conn",
    version=__version__,

    author=u"Tam\u00e1s Nepusz",
    author_email="tamas@collmot.com",

    packages=find_packages(exclude=["test"]),
    include_package_data=True,
    install_requires=requires,
    test_suite="test"
)
