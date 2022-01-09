from setuptools import setup, find_packages

setup(
    name='cronitor',
    version='4.3.1',
    packages=find_packages(),
    url='https://github.com/cronitorio/cronitor-python',
    license='MIT License',
    author='August Flanagan',
    author_email='august@cronitor.io',
    description='A lightweight Python client for Cronitor.',
    install_requires=[
        'requests',
        'pyyaml',
        'humanize',
    ],
    entry_points=dict(console_scripts=['cronitor = cronitor.__main__:main'])
)
