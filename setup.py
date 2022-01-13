from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='cronitor',
    version='4.4.2',
    packages=find_packages(),
    url='https://github.com/cronitorio/cronitor-python',
    license='MIT License',
    author='August Flanagan',
    author_email='august@cronitor.io',
    description='A lightweight Python client for Cronitor.',
    long_description = long_description,
    long_description_content_type = 'text/markdown',
    install_requires=[
        'requests',
        'pyyaml',
        'humanize',
    ],
    entry_points=dict(console_scripts=['cronitor = cronitor.__main__:main'])
)
