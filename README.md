# Bot SMC para Binance Futures

Bot de trading algorítmico basado en **Smart Money Concepts (SMC)** para ETH/USDT y BTC/USDT perpetuos en Binance Futures.

## Características principales

- **7 filtros obligatorios** SMC (tendencia macro, liquidity sweep, order block, RSI, confluencias, volumen institucional, R:R ≥ 1:2)
- **Sistema de scoring 0-10** con tamaño de posición ajustado al score
- **Multi-timeframe**: análisis 15m → 1H → 4H
- **Gestión de riesgo integrada**: drawdown diario/semanal, máximo de posiciones simultáneas, trailing stops post-TP1
- **3 modos de ejecución**: LIVE, PAPER TRADING (testnet), DRY RUN (simulado)
- **Notificaciones Telegram** con formato detallado
- **Backtesting** con métricas profesionales (win rate, profit factor, Sharpe, drawdown)
- **Persistencia SQLite** de trades y estado
- **24/7 ready**: reconexión automática, recuperación tras reinicio

## Estructura

```
bot_trading/
├── main.py                  # Loop principal con APScheduler
├── config.py                # Parámetros centralizados
├── backtest.py              # Backtester
├── requirements.txt
├── .env.example             # Plantilla de credenciales
│
├── exchange/
│   ├── binance_client.py    # Wrapper Binance Futures
│   ├── order_manager.py     # SL/TP escalonados (40/40/20)
│   └── position_tracker.py  # Estado de posiciones
│
├── indicators/
│   ├── ema_calculator.py    # EMA 7/25/99
│   ├── supertrend.py        # Supertrend(10, 3)
│   ├── bollinger.py         # BB(20, 2)
│   ├── rsi_calculator.py    # RSI(6) y RSI(14)
│   └── volume_analyzer.py   # Volumen + MA(5) MA(10)
│
├── strategy/
│   ├── filter_engine.py     # Los 7 filtros SMC
│   ├── scoring_system.py    # Score 0-10
│   ├── signal_detector.py   # Patrones complementarios
│   └── risk_manager.py      # Drawdown, trailing, cooldown
│
├── data/
│   ├── candle_fetcher.py    # OHLCV desde Binance
│   ├── multi_tf_analyzer.py # Pipeline 15m/1H/4H
│   └── database.py          # SQLite
│
└── notifications/
    ├── telegram_bot.py      # Alertas Telegram
    └── log_formatter.py     # Formato legible
```

## Instalación

```bash
git clone <tu-repo>
cd bot_trading
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus credenciales
```

## Variables de entorno (.env)

```
TESTNET=true
DRY_RUN=true
PAPER_TRADING=true
BINANCE_API_KEY=tu_key
BINANCE_API_SECRET=tu_secret
TELEGRAM_BOT_TOKEN=opcional
TELEGRAM_CHAT_ID=opcional
LOG_LEVEL=INFO
```

## Modos de operación

| Modo | TESTNET | DRY_RUN | Descripción |
|------|---------|---------|-------------|
| **DRY RUN** | true | true | Simula todo, no envía órdenes (recomendado para empezar) |
| **PAPER TRADING** | true | false | Opera en testnet de Binance con dinero ficticio |
| **LIVE** | false | false | ⚠️ Dinero real - solo tras backtest exitoso |

## Uso

### Backtest (OBLIGATORIO antes de live)

```bash
python backtest.py --symbol ETHUSDT --months 6
```

Métricas mínimas aceptables:
- Win rate ≥ 45%
- Profit factor ≥ 1.5
- Max drawdown ≤ 20%
- Sharpe ≥ 1.5
- Mínimo 100 trades

### Ejecución del bot

```bash
python main.py
```

### Despliegue 24/7 en VPS (con systemd)

Crear `/etc/systemd/system/bot-smc.service`:

```ini
[Unit]
Description=Bot SMC Trading
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bot_trading
ExecStart=/home/ubuntu/bot_trading/venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bot-smc
sudo systemctl start bot-smc
sudo journalctl -fu bot-smc
```

## Lógica de los 7 filtros

| # | Filtro | Crítico | Descripción |
|---|--------|---------|-------------|
| 1 | Tendencia macro | ✅ | Supertrend ≥2/3 TF + EMAs en cascada 4H y 1H |
| 2 | Liquidity sweep | ✅ | Mecha barre nivel previo SIN cierre fuera |
| 3 | Order Block | – | OB no mitigado, entrada en 50% del rango |
| 4 | RSI doble | ✅ | RSI(14) 1H en rango + RSI(6) sin extremos |
| 5 | Confluencias | – | Mínimo 3/5: Fib, FVG+OB, BB, ST S/R, BOS |
| 6 | Volumen institucional | – | Vela sweep > 1.5x MA(10), pullback decreciente |
| 7 | Risk/Reward ≥ 1:2 | ✅ | SL ≤ 1.5%, TP1 ≥ 2x SL |

Si cualquier filtro **crítico** falla → no operar.

## Sistema de scoring → tamaño

| Score | Categoría | % Capital |
|-------|-----------|-----------|
| 9-10 | Perfecto | 2.0% |
| 7-8 | Bueno | 1.5% |
| 5-6 | Débil | 1.0% |
| <5 | Inválido | NO OPERAR |

## Avisos importantes

- ⚠️ Trading apalancado conlleva **alto riesgo de pérdida**
- ⚠️ Probar **siempre** en DRY_RUN → PAPER → LIVE en ese orden
- ⚠️ Empezar con tamaño pequeño tras primer mes en live
- ⚠️ Monitorear drawdown diario; el bot se autodetiene al 5%
- ⚠️ El backtest no garantiza resultados futuros

## Licencia / disclaimer

Este código es educativo. El uso en trading real es responsabilidad del usuario.
No constituye consejo financiero.
