"""
Configuration loader for SMC4 trading project.
All secrets and parameters are loaded from .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """Central configuration object."""

    # --- API Keys ---
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")

    # --- Strategy Parameters ---
    SYMBOL: str = os.getenv("SYMBOL", "BTCUSDT")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "1h")
    LOOKBACK_PERIOD: int = int(os.getenv("LOOKBACK_PERIOD", "20"))
    CONFIRMATION_BARS: int = int(os.getenv("CONFIRMATION_BARS", "3"))
    RISK_REWARD_RATIO: float = float(os.getenv("RISK_REWARD_RATIO", "2.0"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "1.5"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "3.0"))

    # --- Backtest ---
    INITIAL_BALANCE: float = float(os.getenv("INITIAL_BALANCE", "10000.0"))
    COMMISSION_PCT: float = float(os.getenv("COMMISSION_PCT", "0.05"))
    SLIPPAGE_PCT: float = float(os.getenv("SLIPPAGE_PCT", "0.02"))
    TRAIN_MONTHS: int = int(os.getenv("TRAIN_MONTHS", "6"))
    TEST_MONTHS: int = int(os.getenv("TEST_MONTHS", "2"))
    WALK_FORWARD_STEP: int = int(os.getenv("WALK_FORWARD_STEP", "1"))

    # --- Optimization ---
    OPTUNA_TRIALS: int = int(os.getenv("OPTUNA_TRIALS", "100"))
    OPTUNA_METRIC: str = os.getenv("OPTUNA_METRIC", "sharpe_ratio")

    # --- Paths ---
    DATA_DIR: Path = PROJECT_ROOT / "data"
    RESULTS_DIR: Path = PROJECT_ROOT / "results"

    @classmethod
    def ensure_dirs(cls):
        cls.DATA_DIR.mkdir(exist_ok=True)
        cls.RESULTS_DIR.mkdir(exist_ok=True)

    @classmethod
    def as_dict(cls) -> dict:
        """Return config as dict for logging/reproducibility."""
        return {
            k: v for k, v in cls.__dict__.items()
            if not k.startswith("_") and not callable(v)
        }


config = Config()
config.ensure_dirs()
