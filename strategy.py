"""
SMC (Smart Money Concepts) strategy implementation.
This is a simplified version — replace with your actual logic.
"""
import pandas as pd
import numpy as np


def calculate_indicators(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Calculate base indicators for SMC strategy."""
    df = df.copy()

    df["sma"] = df["close"].rolling(window=lookback).mean()

    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["close"].shift()),
            abs(df["low"] - df["close"].shift()),
        ),
    )
    df["atr"] = df["tr"].rolling(window=lookback).mean()

    df["swing_high"] = df["high"].rolling(window=lookback).max()
    df["swing_low"] = df["low"].rolling(window=lookback).min()

    return df


def generate_signals(
    df: pd.DataFrame,
    lookback: int = 20,
    confirmation_bars: int = 3,
    risk_reward: float = 2.0,
    sl_pct: float = 1.5,
    tp_pct: float = 3.0,
) -> pd.DataFrame:
    """
    Generate entry/exit signals for SMC strategy.

    Returns DataFrame with columns:
    - signal: 1 (long), -1 (short), 0 (flat)
    - stop_loss, take_profit (prices)
    """
    df = calculate_indicators(df, lookback)
    df["signal"] = 0
    df["stop_loss"] = np.nan
    df["take_profit"] = np.nan

    for i in range(lookback + confirmation_bars, len(df)):
        window = df.iloc[i - confirmation_bars:i]

        if (
            len(window) >= confirmation_bars
            and (window["close"].diff() > 0).all()
            and df.iloc[i]["close"] > df.iloc[i - 1]["swing_high"]
        ):
            entry_price = df.iloc[i]["close"]
            df.loc[df.index[i], "signal"] = 1
            df.loc[df.index[i], "stop_loss"] = entry_price * (1 - sl_pct / 100)
            df.loc[df.index[i], "take_profit"] = entry_price * (1 + tp_pct / 100)

        elif (
            len(window) >= confirmation_bars
            and (window["close"].diff() < 0).all()
            and df.iloc[i]["close"] < df.iloc[i - 1]["swing_low"]
        ):
            entry_price = df.iloc[i]["close"]
            df.loc[df.index[i], "signal"] = -1
            df.loc[df.index[i], "stop_loss"] = entry_price * (1 + sl_pct / 100)
            df.loc[df.index[i], "take_profit"] = entry_price * (1 - tp_pct / 100)

    return df
