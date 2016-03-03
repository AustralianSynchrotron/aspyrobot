from setuptools import setup
import re

with open('pyrobot/__init__.py', 'r') as f:
    version = re.search(r"__version__ = '(.*)'", f.read()).group(1)

setup(
    name='pyrobot',
    version=version,
    packages=['pyrobot'],
    install_requires=[
        'pyzmq>=15.1.0',
        'pyepics>=3.2.5rc3',
        'numpy>=1.10.2',
        'six>=1.10.0',
    ],
)
