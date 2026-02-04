# Solana VWAP Trading Agent

**Autonomous mean reversion trading on Solana DEXes.**

## What It Does

AI agent that monitors Solana DEX prices, detects VWAP deviations, and executes mean reversion trades automatically.

## Why Solana

| Feature | Advantage |
|---------|-----------|
| **400ms block time** | Faster execution than Ethereum |
| **$0.002 fees** | Profitable on smaller edges |
| **Jupiter aggregation** | Best price across all DEXes |
| **MEV protection** | Jito bundles prevent frontrunning |

## Strategy

**VWAP Mean Reversion:**
- Calculate VWAP from recent trades
- When price extends 0.5%+ beyond VWAP → reversal likely
- Enter position toward VWAP
- Exit when price reverts or hits stop

**Risk Management:**
- 1% risk per trade
- 1.5:1 R/R minimum
- Max 3 open positions
- Daily stop-loss: -5%

## Architecture

```
Price Feed → VWAP Engine → Signal Generator → Jupiter Executor
                 ↓
         On-Chain Position Tracking (PDA)
                 ↓
         Telegram Alerts
```

## Solana Integration

- **Jupiter Swap API:** Execute trades at best price
- **Pyth Network:** Price feeds for VWAP calculation  
- **Solana Pay:** Optional payment integration
- **Anchor Framework:** On-chain position tracking

## Project Tags

`defi`, `ai`, `trading`

## Links

- Repo: [To be created]
- Demo: [To be deployed]

## Prize Goal

$50,000 (1st place) — Build the most autonomous trading agent on Solana.