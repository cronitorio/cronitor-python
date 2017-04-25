from setuptools import setup, find_packages

setup(
    name='cronitor',
    version='1.0.2',
    packages=find_packages(),
    url='https://github.com/vy-labs/cronitor',
    license='MIT License',
    author='xrage',
    author_email='',
    description='Python wrapper for cronitor monitors',
    install_requires=[
        'requests',
    ],
    entry_points={'console_scripts': [
                     'cronitor = cronitor.monitor:main'
                  ]
    },
)
