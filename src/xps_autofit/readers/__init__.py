"""File readers.  :func:`read_spectra` dispatches on extension (or content)."""

from .reader_registry import read_spectra, register_reader, supported_extensions

__all__ = ["read_spectra", "register_reader", "supported_extensions"]
