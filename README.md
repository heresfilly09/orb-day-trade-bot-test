# ORB Day Trading Bot — ES Futures

Opening Range Breakout (ORB) strategy bot for E-mini S&P 500 (ES) futures. Tracks the first 30 minutes of NYSE open (9:30–10:00 ET), then trades breakouts above/below that range.

## Strategy

1. **Build the opening range** — record the high and low of ES during 9:30–10:00 ET
2. **Wait for breakout** — a candle closes beyond the range (plus a configurable buffer)
3. **Enter** — long on upside breakout, short on downside breakout
4. **Manage** — stop loss at opposite side of range, profit target at configurable R:R
5. **Flatten** — all positions closed by 3:45 PM ET

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Generate sample 1-min data for testing
python main.py generate-sample-data --days 10

# Backtest on historical data
python main.py backtest --data data/es_sample.csv

# Paper trade (replays data with simulated broker)
python main.py paper --data data/es_sample.csv
```

## Configuration

Edit `config.yaml` to adjust:

- **Opening range window** and breakout buffer
- **Range size filters** (skip days with too-wide or too-narrow ranges)
- **Risk management** — stop loss buffer, R:R ratio, daily loss limit, max trades/day
- **Trailing stops** — optional, activates after 1R profit
- **Retest mode** — wait for price to retest the breakout level before entry
- **Position sizing** — number of contracts

## Project Structure

```
main.py                  # CLI entry point
config.yaml              # Strategy and risk parameters
orb_bot/
  strategy.py            # Core ORB strategy logic
  models.py              # Data models (Trade, PriceBar, OpeningRange)
  backtest.py            # Backtest engine for CSV data
  live.py                # Live/paper trading runner + broker interfaces
  journal.py             # Trade journal CSV writer
tests/
  test_strategy.py       # Unit tests for strategy logic
```

## Live Trading

The `live.py` module provides abstract `DataFeed` and `Broker` classes. To connect to a real broker:

1. Implement `DataFeed` for your market data provider (e.g., Interactive Brokers, Tradovate, Rithmic)
2. Implement `Broker` for order execution
3. Set `paper_trade: false` in config.yaml

**Important:** This bot is for educational purposes. Always test thoroughly in paper mode before risking real capital. Futures trading involves substantial risk of loss.
