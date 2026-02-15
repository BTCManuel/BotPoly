# Polymarket BTC 5m Up/Down Bot (MVP+)

Async Python 3.11+ Bot für den **Polymarket Bitcoin Up/Down 5-Minuten-Markt**.

## Features
- Binance BTCUSDT Trade-Feed (WebSocket)
- Polymarket CLOB Market-Feed (WebSocket)
- Auto Market Discovery **und automatische Market-Rotation** (5-Min-Fenster)
- Live Decision-Snapshots in der Konsole (`--verbose`)
- Einfache, robuste Signal-Logik (Momentum + Realized Volatility)
- `paper` (default) + optional `live`
- Risk Controls: max exposure, cooldown, daily loss kill switch
- Exit-Logik: Profit-Take + Time-Stop
- SQLite Speicherung: ticks, orders, fills, positions, pnl, errors
- Retry/Reconnect mit `tenacity`

## Installation
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Konfiguration
Alle Secrets **nur via ENV** (`.env`).

Wichtige Parameter für Debug/Trading-Frequenz:
- `EDGE_MIN` (z. B. `0.01` bis `0.04`)
- `MAX_SPREAD` (z. B. `0.02` bis `0.03`)
- `LOOP_INTERVAL_SECONDS` (default `1.0`)
- `ROTATE_INTERVAL_SECONDS` (default `300`)
- `PAPER_FILL_EPSILON` (default `0.0`)
- `ALLOW_CROSS_WINDOW_POSITIONS` (default `false`)
- `MARKET_DISCOVERY_FALLBACK_SECONDS` (default `120`)

## Start
```bash
python -m bot run --mode paper --hours 0.17 --verbose
```

oder explizit live:
```bash
python -m bot run --mode live --hours 1
```

Ergebnis-Auswertung:
```bash
python -m bot report --mode paper
```

## Market Rotation
- Der Bot discovered initial den aktiven `btc-updown-5m-<unix_ts>` Markt.
- Danach läuft ein Scheduler (`ROTATE_INTERVAL_SECONDS`), der den Markt neu discovered.
- Bei Wechsel wird `market_rotated` geloggt (alter/neuer slug + token ids).
- Offene Positionen bleiben gemanagt; neue Trades nutzen den neuen Markt.

## Warum ggf. 0 Trades?
Wenn `orders_total=0`, nutze `--verbose` und prüfe Reason-Codes pro Tick:
- `edge_too_low`
- `spread_too_wide`
- `cooldown_active`
- `max_exposure_hit`
- `daily_loss_limit_hit`
- `position_open_old_window`

Wenn während Laufzeit kein Entry-Signal entsteht, schreibt der Bot am Ende ein `no_trades_summary` mit:
- reason breakdown
- min/max/avg von Edge_UP/Edge_DOWN
- min/max/avg von Spread_UP/Spread_DOWN

## Datenbank
Default: `bot.db`
Tabellen:
- `ticks` (Decision Snapshots)
- `orders`
- `fills`
- `positions`
- `pnl`
- `errors`

## Hinweise zu LIVE MODE
- Live Mode ist optional und absichtlich nicht default.
- Vor Live-Start:
  1. Wallet + API Credentials korrekt setzen.
  2. Paper-Mode mindestens mehrere Sessions laufen lassen.
  3. Max-Risiko klein halten.

## Haftung
Nur Forschungs-/Lernzwecke. Keine Anlageberatung.
