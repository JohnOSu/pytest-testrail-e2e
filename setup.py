from setuptools import setup


def read_file(fname):
    with open(fname) as f:
        return f.read()


setup(
    name='pytest-testrail-e2e',
    description='pytest plugin for creating TestRail runs and adding results',
    long_description=read_file('README.rst'),
    version='3.0.4',
    author='NGUYEN Viet',
    author_email='vietnq254@live.com',
    url='https://github.com/vietnq254/pytest-testrail-e2e/',
    packages=[
        'pytest_testrail',
    ],
    package_dir={'pytest_testrail_e2e': 'pytest_testrail_e2e'},
    install_requires=[
        'pytest>=3.6',
        'requests>=2.20.0',
    ],
    include_package_data=True,
    entry_points={'pytest11': ['pytest-testrail-e2e = pytest_testrail.conftest']},
)
