import sys

import ffcoach


def test_version_is_exposed():
    assert ffcoach.__version__ == "0.1.0"


def test_running_on_python_312_or_newer():
    assert sys.version_info >= (3, 12)
