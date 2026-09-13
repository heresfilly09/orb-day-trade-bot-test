# ORB Day Trading Bot — ES Futures

Opening Range Breakout (ORB) strategy bot for E-mini S&P 500 (ES) futures. Uses the first two 15-minute candles at NYSE open (9:30–10:00 ET) to define the range, then trades breakouts with stop loss at the opposite end. Works on other futures and forex with adjusted parameters.

## Strategy

1. **Build the range** — high/low of the first two 15-min candles (9:30–9:45, 9:45–10:00 ET)
2. **Breakout** — price closes beyond range + buffer → go long (above) or short (below)
3. **Filters** — EMA trend, VWAP, RSI extremes, volume confirmation, range size limits
4. **Stop loss** — opposite end of the range + buffer
5. **Profit target** — configurable R:R ratio (default 1:1)
6. **Breakeven** — SL moves to entry when trade reaches 1R profit
7. **Cutoff** — no new entries after 11:00 ET, max 1 trade/day
8. **Flatten** — all positions closed by 3:45 PM ET

## Filters

| Filter | Default | Purpose |
|--------|---------|---------|
| EMA (50) | ON | Only long above EMA, short below |
| VWAP | ON | Intraday trend confirmation |
| RSI (14) | ON | Skip longs >70, shorts <30 |
| Volume | ON | Breakout bar must exceed average volume |
| Range size | 5–15 pts | Skip too-tight or too-wide days |
| Breakout buffer | 1.0 pt | Price must close beyond range by this amount |
| Time cutoff | 11:00 ET | No entries after this time |

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

## TradingView

1. Open Pine Editor → paste `orb_30min_breakout.pine` → Add to Chart
2. Use **15-min or 30-min** timeframe on ES1! for best results
3. Set up alerts: right-click the strategy → Add Alert → choose "ORB Long Breakout" or "ORB Short Breakout"

Available alerts: Long Breakout, Short Breakout, Range Set, Range Skipped, Session End.

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
| `orb_30min_breakout.pine` | TradingView strategy — backtestable ORB breakout with alerts |
| `orb_strategy.py` | Core ORB strategy logic with all filters |
| `risk_manager.py` | Trade journaling and daily summary CSV output |
| `tradovate_client.py` | Tradovate REST API client for order execution |

## Output Files (generated)

| File | Content |
|------|---------|
| `orb_trades.csv` | Individual trade log |
| `orb_summary.csv` | Daily PnL summary |
| `orb_bot.log` | Runtime log |
