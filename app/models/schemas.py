"""
Schemas/Enums module.

Defines the Enums/Schemas needed by the application.
"""

from enum import Enum


class SourceType(str, Enum):
    """
    Enumeration of supported content sources.

    Attributes:
        DEVTO: Dev.to platform
        REDDIT: Reddit r/programming
        LOBSTERS: Lobsters tech aggregator
    """

    DEVTO = "Dev.to"
    REDDIT = "Reddit"
    LOBSTERS = "Lobsters"
