# -*- coding: utf-8 -*-

"""
To upload to PyPI, PyPI test, or a local server:
python setup.py bdist_wheel upload -r <server_identifier>
"""

import setuptools

setuptools.setup(
    name="MultiAcquire",
    version="0.1",
    author="Andreas Mittelberger",
    author_email="Brow71189@gmail.com",
    description="A Nion Swift plug-in to acquire HDR and stitched EELS spectra",
    url="https://github.com/Brow71189/MultiEELS",
    packages=["nionswift_plugin.multi_acquire", "multi_acquire_utils", "multi_acquire_utils.test"],
    install_requires=['nionswift>=0.14.3', 'nionswift-instrumentation'],
    license='MIT',
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Programming Language :: Python :: 3.6",
    ],
    python_requires='~=3.6',
    zip_safe=False,
    test_suite="multi_acquire_utils.test"
)
