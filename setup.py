from setuptools import setup, find_packages

setup(
    name='cronitor',
    version='4.1.0',
    packages=find_packages(),
    url='https://github.com/cronitorio/cronitor-python',
    license='MIT License',
    author='aflanagan',
    author_email='',
    description='A lightweight Python client for Cronitor.',
    install_requires=[
        'requests',
        'pyyaml'
    ],
    entry_points=dict(console_scripts=['cronitor = cronitor.__main__:main'])
)
