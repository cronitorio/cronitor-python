from distutils.core import setup

install_requires = [
    'requests'
]

setup(
    name='cronitor',
    version='1.0',
    packages=[''],
    url='https://github.com/vylabs/cronitor',
    license='MIT License',
    author='dkverma',
    author_email='',
    description='Python wrapper for cronitor monitors',
    install_requires=install_requires
)
