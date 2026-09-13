# ORB Day Trading Bot — ES Futures

Opening Range Breakout (ORB) strategy bot for E-mini S&P 500 (ES) futures. Uses the first two 15-minute candles at NYSE open (9:30–10:00 ET) to define the range, then trades breakouts with stop loss at the opposite end.

## Strategy

1. **Build the range** — high/low of the first two 15-min candles (9:30–9:45, 9:45–10:00 ET)
2. **Breakout** — price closes above range high → go long; below range low → go short
3. **Stop loss** — opposite end of the range
4. **Profit target** — configurable R:R ratio (default 2:1)
5. **Flatten** — all positions closed by 3:45 PM ET

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # Fill in Tradovate credentials
```

## Usage

```bash
# Generate sample data and backtest
python backtest_orb.py --generate --days 10
python backtest_orb.py --data es_sample_data.csv

# Run paper trading
python main.py

# Run live with Tradovate
python main.py --live
```

## Files

| File | Purpose |
|------|---------|
| `.env.example` | Tradovate API credentials template |
| `backtest_orb.py` | Backtest engine — runs strategy on historical CSV data |
| `candle_builder.py` | Builds 15-min candles from tick/1-min data |
| `config.py` | Loads config.yaml + .env credentials |
| `config.yaml` | Strategy, risk, and trading parameters |
| `main.py` | Live/paper trading entry point |
| `orb_30min.pine` | TradingView indicator — plots the 30-min opening range |
| `orb_30min_breakout.pine` | TradingView strategy — backtestable ORB breakout |
| `orb_strategy.py` | Core ORB strategy logic |
| `risk_manager.py` | Trade journaling and daily summary CSV output |
| `tradovate_client.py` | Tradovate REST API client for order execution |

## Output Files (generated)

| File | Content |
|------|---------|
| `orb_trades.csv` | Individual trade log |
| `orb_summary.csv` | Daily PnL summary |
| `orb_bot.log` | Runtime log |
