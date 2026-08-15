#!"/the one/software/python/bin/python" -B

"""T1OS system Python module service."""

import importlib.util
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_manager():
    """Load pip.py without claiming the import name used by upstream pip."""
    path = os.path.join(ROOT, 'pip.py')
    specification = importlib.util.spec_from_file_location(
        '_t1os_python_module_manager', path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError('The T1OS Python module manager is unavailable.')
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


if __name__ == '__main__':
    raise SystemExit(load_manager().main())
