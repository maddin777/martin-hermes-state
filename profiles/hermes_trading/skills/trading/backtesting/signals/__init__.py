"""Signal-Modelle für den Backtester.

Verfügbare Modelle:
- PEADModel: Post-Earnings-Announcement Drift (Quant)
- SignalExtractorModel: Wrapper um die existierende Pipeline-Signale
"""

from backtesting.signals.pead import PEADModel
from backtesting.signals.signal_extractor import SignalExtractorModel

__all__ = ["PEADModel", "SignalExtractorModel"]