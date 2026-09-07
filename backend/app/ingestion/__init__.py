"""Ingestion adapters: raw sources → canonical model (PRD §5.1, §6)."""

from .tcx_parser import parse_tcx, parse_tcx_file
from .scale_reader import read_scale_xls
from .treadmill_log import build_treadmill_workout, parse_treadmill_log

__all__ = [
    "parse_tcx",
    "parse_tcx_file",
    "read_scale_xls",
    "build_treadmill_workout",
    "parse_treadmill_log",
]
