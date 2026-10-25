"""Validate inventory exports without executing a documentation configuration."""
from .core import AuditError, audit, read_inventory

__version__ = "0.1.0"
__all__ = ["AuditError", "audit", "read_inventory"]
