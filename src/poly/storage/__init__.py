"""Database and storage backends."""

from .sqlite import SQLiteWriter
from .db_writer import get_db_writer, DBWriter

# Bigtable is optional (requires google-cloud-bigtable)
try:
    from .bigtable import BigtableWriter, BigtableConfig
except ImportError:
    BigtableWriter = None
    BigtableConfig = None


__all__ = [
    "SQLiteWriter",
    "get_db_writer",
    "DBWriter",
    "BigtableWriter",
    "BigtableConfig",
]
