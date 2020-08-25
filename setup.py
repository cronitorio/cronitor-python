from setuptools import setup, find_packages

setup(
    name='cronitor',
    version='2.0.2',
    packages=find_packages(),
    url='https://github.com/cronitorio/cronitor-python',
    license='MIT License',
    author='aflanagan',
    author_email='',
    description='A lightweight Python client for Cronitor\'s API.',
    install_requires=[
        'requests',
    ],
    entry_points=dict(console_scripts=['cronitor = cronitor.__main__:main'])
)
