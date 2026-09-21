"""
Backtest and parameter optimization for SMC strategy.
Uses Optuna for hyperparameter search and walk-forward validation.
"""
import pandas as pd
import numpy as np
import optuna
from config import config
from strategy import generate_signals

optuna.logging.set_verbosity(optuna.logging.WARNING)


def load_data(symbol: str, timeframe: str) -> pd.DataFrame:
    """Load historical data from CSV or generate synthetic for testing."""
    data_path = config.DATA_DIR / f"{symbol}_{timeframe}.csv"

    if data_path.exists():
        df = pd.read_csv(data_path, parse_dates=["timestamp"])
        df.set_index("timestamp", inplace=True)
        return df

    print(f"⚠️  Data file not found: {data_path}")
    print("Generating synthetic data for testing...")
    return generate_synthetic_data()


def generate_synthetic_data(n_bars: int = 2000) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="1h")
    close = 50000 + np.cumsum(np.random.randn(n_bars) * 100)

    df = pd.DataFrame({
        "open": close + np.random.randn(n_bars) * 50,
        "high": close + np.abs(np.random.randn(n_bars) * 150),
        "low": close - np.abs(np.random.randn(n_bars) * 150),
        "close": close,
        "volume": np.random.randint(100, 1000, n_bars),
    }, index=dates)

    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def run_backtest(df: pd.DataFrame, params: dict) -> dict:
    """Run backtest with given parameters."""
    df = generate_signals(
        df,
        lookback=params["lookback"],
        confirmation_bars=params["confirmation_bars"],
        risk_reward=params["risk_reward"],
        sl_pct=params["stop_loss_pct"],
        tp_pct=params["take_profit_pct"],
    )

    balance = config.INITIAL_BALANCE
    equity_curve = [balance]
    trades = []
    position = 0
    entry_price = 0
    stop_loss = 0
    take_profit = 0

    commission = config.COMMISSION_PCT / 100
    slippage = config.SLIPPAGE_PCT / 100

    for i in range(1, len(df)):
        row = df.iloc[i]

        if position != 0:
            exit_price = None
            if position == 1:
                if row["low"] <= stop_loss:
                    exit_price = stop_loss
                elif row["high"] >= take_profit:
                    exit_price = take_profit
            else:
                if row["high"] >= stop_loss:
                    exit_price = stop_loss
                elif row["low"] <= take_profit:
                    exit_price = take_profit

            if exit_price is not None:
                if position == 1:
                    exit_price *= (1 - slippage)
                else:
                    exit_price *= (1 + slippage)

                pnl_pct = (exit_price / entry_price - 1) * position
                pnl = balance * pnl_pct - balance * commission
                balance += pnl
                trades.append(pnl_pct)
                position = 0

        if position == 0 and row["signal"] != 0:
            entry_price = row["close"]
            if row["signal"] == 1:
                entry_price *= (1 + slippage)
            else:
                entry_price *= (1 - slippage)

            stop_loss = row["stop_loss"]
            take_profit = row["take_profit"]
            position = row["signal"]

        equity_curve.append(balance)

    equity = pd.Series(equity_curve)
    returns = equity.pct_change().dropna()

    if len(returns) == 0 or returns.std() == 0:
        return {"sharpe_ratio": -999, "max_drawdown": 0, "winrate": 0,
                "profit_factor": 0, "total_return": 0, "n_trades": 0}

    sharpe = (returns.mean() / returns.std()) * np.sqrt(24 * 365)
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = drawdown.min()

    winrate = sum(1 for t in trades if t > 0) / len(trades) if trades else 0
    gross_profit = sum(t for t in trades if t > 0)
    gross_loss = abs(sum(t for t in trades if t < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999

    return {
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "winrate": winrate,
        "profit_factor": profit_factor,
        "total_return": (balance / config.INITIAL_BALANCE - 1) * 100,
        "n_trades": len(trades),
    }


def objective(trial: optuna.Trial, df: pd.DataFrame) -> float:
    """Optuna objective function."""
    params = {
        "lookback": trial.suggest_int("lookback", 10, 100, step=5),
        "confirmation_bars": trial.suggest_int("confirmation_bars", 2, 10),
        "risk_reward": trial.suggest_float("risk_reward", 1.0, 4.0, step=0.25),
        "stop_loss_pct": trial.suggest_float("stop_loss_pct", 0.5, 5.0, step=0.25),
        "take_profit_pct": trial.suggest_float("take_profit_pct", 1.0, 10.0, step=0.5),
    }

    metrics = run_backtest(df, params)

    for key, value in metrics.items():
        trial.set_user_attr(key, value)

    return metrics.get(config.OPTUNA_METRIC, -999)


def walk_forward_optimization(df: pd.DataFrame) -> pd.DataFrame:
    """Walk-forward optimization."""
    df_monthly = df.resample("ME").last()
    months = df_monthly.index

    train_bars = config.TRAIN_MONTHS
    test_bars = config.TEST_MONTHS
    step = config.WALK_FORWARD_STEP

    results = []

    for start in range(0, len(months) - train_bars - test_bars, step):
        train_end = start + train_bars
        test_end = train_end + test_bars

        if test_end > len(months):
            break

        train_start_date = months[start]
        train_end_date = months[train_end - 1]
        test_start_date = months[train_end]
        test_end_date = months[test_end - 1]

        train_df = df.loc[train_start_date:train_end_date]
        test_df = df.loc[test_start_date:test_end_date]

        print(f"\n📊 Walk-forward window {start // step + 1}")
        print(f"   Train: {train_start_date.date()} → {train_end_date.date()}")
        print(f"   Test:  {test_start_date.date()} → {test_end_date.date()}")

        study = optuna.create_study(direction="maximize")
        study.optimize(
            lambda t: objective(t, train_df),
            n_trials=config.OPTUNA_TRIALS,
            show_progress_bar=True,
        )

        best_params = study.best_params
        train_metrics = run_backtest(train_df, best_params)
        test_metrics = run_backtest(test_df, best_params)

        results.append({
            "window": start // step + 1,
            "train_start": train_start_date,
            "train_end": train_end_date,
            "test_start": test_start_date,
            "test_end": test_end_date,
            **{f"train_{k}": v for k, v in train_metrics.items()},
            **{f"test_{k}": v for k, v in test_metrics.items()},
            **{f"param_{k}": v for k, v in best_params.items()},
        })

        print(f"   Train Sharpe: {train_metrics['sharpe_ratio']:.2f}")
        print(f"   Test  Sharpe: {test_metrics['sharpe_ratio']:.2f}")
        print(f"   Best params:  {best_params}")

    return pd.DataFrame(results)


def main():
    print("=" * 60)
    print("SMC Strategy Optimization")
    print("=" * 60)

    df = load_data(config.SYMBOL, config.TIMEFRAME)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    results = walk_forward_optimization(df)

    output_path = config.RESULTS_DIR / "optimization_results.csv"
    results.to_csv(output_path, index=False)
    print(f"\n✅ Results saved to {output_path}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Windows tested: {len(results)}")
    print(f"Avg Test Sharpe: {results['test_sharpe_ratio'].mean():.2f}")
    print(f"Avg Test Return: {results['test_total_return'].mean():.2f}%")
    print(f"Avg Test Winrate: {results['test_winrate'].mean():.2%}")
    print(f"Avg Test Max DD: {results['test_max_drawdown'].mean():.2%}")

    best_idx = results["test_sharpe_ratio"].idxmax()
    print(f"\n🏆 Best window: {results.loc[best_idx, 'window']}")
    print(f"   Test Sharpe: {results.loc[best_idx, 'test_sharpe_ratio']:.2f}")


if __name__ == "__main__":
    main()
