"""Bundled model artifacts.

This subpackage exists so ``importlib.resources.files("data_classifier.models")``
resolves to a real package inside both editable installs and installed wheels.
The artifacts themselves (``*.pkl``, ``*.json``) are declared under
``[tool.setuptools.package-data]`` in pyproject.toml.
"""
