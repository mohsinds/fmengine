"""Built-in strategy library."""

from fmtrader.strategy.library import (
    bollinger_breakout,
    buy_and_hold,
    ema_cross,
    macd_cross,
    rsi_mean_reversion,
    supertrend_trend,
)

__all__ = [
    "bollinger_breakout",
    "buy_and_hold",
    "ema_cross",
    "macd_cross",
    "rsi_mean_reversion",
    "supertrend_trend",
]
