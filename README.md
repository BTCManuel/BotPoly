# Polymarket BTC 5m Up/Down Bot (MVP)

Async Python 3.11+ Bot für den **Polymarket Bitcoin Up/Down 5-Minuten-Markt**.

## Features
- Binance BTCUSDT Trade-Feed (WebSocket)
- Polymarket CLOB Market-Feed (WebSocket)
- Auto Market Discovery (mit Fallback auf `.env` Token IDs)
- Einfache, robuste Signal-Logik (Momentum + Realized Volatility)
- Nur LIMIT Orders
- `paper` (default) + optional `live`
- Risk Controls: max exposure, cooldown, daily loss kill switch
- Exit-Logik: Profit-Take + Time-Stop
- SQLite Speicherung: ticks, orders, fills, pnl, errors
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

Wichtig:
- Standard ist `MODE=paper`.
- Für Live Trading sind mindestens `POLY_PRIVATE_KEY` (+ idealerweise L2 API Credentials) nötig.
- Falls Discovery keinen Markt findet: `UP_TOKEN_ID` + `DOWN_TOKEN_ID` setzen.

## Start
```bash
python -m bot run
```
oder explizit:
```bash
python -m bot run --mode paper
python -m bot run --mode live
```

Zeitlich begrenzt laufen lassen (z. B. 1h / 24h):
```bash
python -m bot run --mode paper --hours 1
python -m bot run --mode paper --hours 24
```

Einfache Ergebnis-Auswertung (Orders + Realized PnL):
```bash
python -m bot report --mode paper
```

## Discovery: Token IDs
1. Bot versucht automatisch aktive BTC Up/Down Märkte über Gamma API zu finden.
2. Erkennt die Token IDs aus Outcomes (`up`, `down`).
3. Falls fehlerhaft/mehrdeutig: manuell in `.env` setzen (`UP_TOKEN_ID`, `DOWN_TOKEN_ID`).

## Trading-Logik (MVP)
- Modell erzeugt `p_up_model` aus BTC Momentum + Volatilität.
- Marktwahrscheinlichkeit `p_up_mkt` aus Up-Mid-Price.
- Trade nur wenn:
  - `edge >= EDGE_MIN`
  - `spread <= MAX_SPREAD`
- Nur LIMIT Buy/Sell.
- Exit:
  - Profit-Take bei `PROFIT_TAKE_BPS`
  - oder `TIME_STOP_SECONDS`.

## Safety / Risk
- Default konservativ (`ORDER_SIZE_USD=10`, `MAX_POSITION_USD=30`).
- Kill Switch: `DAILY_LOSS_LIMIT_USD`.
- Cooldown zwischen neuen Positionen: `COOLDOWN_SECONDS`.
- **Empfehlung live**: separates Bot-Wallet, sehr kleines Startkapital, enges Monitoring.

## Datenbank
Default: `bot.db`
Tabellen:
- `ticks`
- `orders`
- `fills`
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
