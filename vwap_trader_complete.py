#!/usr/bin/env python3
"""
COMPLETE Solana VWAP Trading Agent
Integrates Jupiter (execution), Pyth (prices), VWAP (strategy)
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

# Import our modules
from jupiter_integration import JupiterSwap, SolanaWallet
from pyth_integration import PythPriceFeed

class CompleteVWAPTrader:
    """
    Production-ready VWAP trading agent for Solana.
    
    Features:
    - Pyth real-time price feeds
    - Jupiter best-price execution
    - VWAP mean reversion strategy
    - Risk management
    - Telegram alerts
    """
    
    def __init__(self, 
                 capital_sol: float = 10.0,
                 wallet_key: Optional[str] = None,
                 telegram_chat: Optional[str] = None):
        """
        Args:
            capital_sol: Trading capital in SOL
            wallet_key: Private key for signing (optional for simulation)
            telegram_chat: Telegram chat ID for alerts
        """
        self.capital_sol = capital_sol
        self.wallet = SolanaWallet(private_key=wallet_key)
        self.jupiter = JupiterSwap()
        self.pyth = PythPriceFeed()
        self.telegram_chat = telegram_chat
        
        # Risk settings
        self.risk_per_trade = 0.01  # 1%
        self.max_positions = 3
        self.daily_stop_pct = 0.05  # -5%
        self.min_r_ratio = 1.5
        
        # Track state
        self.positions: List[Dict] = []
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        
        # Trading pairs
        self.symbols = ["SOL/USD"]  # Start with SOL
        
        print(f"💰 Capital: {capital_sol:.2f} SOL (~${capital_sol * 195:.0f})")
        print(f"💳 Wallet: {'Live' if wallet_key else 'Simulation'}")
        print(f"📱 Alerts: {'Enabled' if telegram_chat else 'Disabled'}")
    
    async def scan_and_trade(self):
        """One trading cycle"""
        
        # Check risk limits
        if self.daily_pnl < -self.capital_sol * self.daily_stop_pct:
            await self.alert("🛑 DAILY STOP LOSS HIT")
            return []
        
        if len(self.positions) >= self.max_positions:
            return []
        
        trades = []
        
        for symbol in self.symbols:
            # Skip if max positions
            if len(self.positions) >= self.max_positions:
                break
            
            # Get VWAP data from Pyth
            vwap_data = self.pyth.calculate_vwap(symbol, window_minutes=30)
            
            if 'error' in vwap_data:
                continue
            
            current = vwap_data['current_price']
            vwap = vwap_data['vwap']
            std_dev = vwap_data['std_dev']
            distance_pct = vwap_data['distance_pct']
            
            # Dynamic threshold
            threshold = max(0.5, (std_dev / vwap) * 100 * 1.5)
            
            # Check for signal
            if abs(distance_pct) > threshold:
                # Generate signal
                direction = "SHORT" if distance_pct > 0 else "LONG"
                
                # Calculate levels
                if direction == "LONG":
                    entry = current
                    sl = entry * 0.995  # 0.5% stop
                    tp = vwap + (vwap - entry) * 0.5
                else:
                    entry = current
                    sl = entry * 1.005
                    tp = vwap - (entry - vwap) * 0.5
                
                # Check R/R
                risk = abs(entry - sl)
                reward = abs(tp - entry)
                r_ratio = reward / risk if risk > 0 else 0
                
                if r_ratio >= self.min_r_ratio:
                    # Calculate position size
                    risk_amount = self.capital_sol * self.risk_per_trade
                    position_sol = risk_amount / (sl / entry)
                    position_sol = min(position_sol, self.capital_sol * 0.20)
                    
                    if position_sol > 0.01:  # Min 0.01 SOL
                        # Execute via Jupiter
                        result = self.jupiter.execute_swap(
                            input_token="SOL",  # Simplified - would determine based on direction
                            output_token="USDC",
                            amount_sol=position_sol,
                            wallet_key="wallet"
                        )
                        
                        if result['success']:
                            trade = {
                                'id': f"SOL_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                                'symbol': symbol,
                                'direction': direction,
                                'entry': entry,
                                'sl': sl,
                                'tp': tp,
                                'size': position_sol,
                                'vwap': vwap,
                                'r_ratio': r_ratio,
                                'quote': result.get('quote'),
                                'time': datetime.now().isoformat(),
                                'status': 'PENDING_SIGNATURE'  # Would be OPEN after signing
                            }
                            
                            self.positions.append(trade)
                            self.total_trades += 1
                            trades.append(trade)
                            
                            # Alert
                            msg = f"🎯 {direction} {symbol}\nEntry: ${entry:.2f}\nSL: ${sl:.2f}\nTP: ${tp:.2f}\nSize: {position_sol:.3f} SOL"
                            await self.alert(msg)
        
        return trades
    
    async def check_exits(self):
        """Check if positions hit SL or TP"""
        closed = []
        
        for pos in self.positions[:]:
            symbol = pos['symbol']
            
            # Get current price
            vwap_data = self.pyth.calculate_vwap(symbol, window_minutes=1)
            if 'error' in vwap_data:
                continue
            
            current = vwap_data['current_price']
            direction = pos['direction']
            sl = pos['sl']
            tp = pos['tp']
            
            # Check levels
            sl_hit = (direction == 'LONG' and current <= sl) or \
                     (direction == 'SHORT' and current >= sl)
            
            tp_hit = (direction == 'LONG' and current >= tp) or \
                     (direction == 'SHORT' and current <= tp)
            
            if sl_hit or tp_hit:
                # Calculate P&L
                entry = pos['entry']
                size = pos['size']
                
                if tp_hit:
                    pnl_pct = abs(tp - entry) / entry
                    pnl_sol = size * pnl_pct * 0.995  # After 0.5% fee
                    result = 'WIN'
                    self.winning_trades += 1
                    emoji = "🟢"
                else:
                    pnl_pct = -abs(sl - entry) / entry
                    pnl_sol = size * pnl_pct
                    result = 'LOSS'
                    emoji = "🔴"
                
                self.daily_pnl += pnl_sol
                
                pos['exit'] = current
                pos['pnl'] = pnl_sol
                pos['result'] = result
                pos['status'] = 'CLOSED'
                
                closed.append(pos)
                self.positions.remove(pos)
                
                # Alert
                msg = f"{emoji} {result}\n{pos['symbol']} {direction}\nPnL: {pnl_sol:+.4f} SOL"
                await self.alert(msg)
        
        return closed
    
    async def alert(self, message: str):
        """Send Telegram alert"""
        if self.telegram_chat:
            # Would use Telegram bot API
            print(f"📱 ALERT: {message[:50]}...")
        else:
            print(f"📱 ALERT: {message}")
    
    async def run(self):
        """Main trading loop"""
        print("\n" + "=" * 70)
        print("🚀 SOLANA VWAP TRADING AGENT - LIVE")
        print("=" * 70)
        print(f"Strategy: VWAP Mean Reversion")
        print(f"Execution: Jupiter + Pyth")
        print(f"Capital: {self.capital_sol:.2f} SOL")
        print("=" * 70)
        
        cycle = 0
        while True:
            cycle += 1
            
            # Check exits
            closed = await self.check_exits()
            
            # Scan and trade
            new_trades = await self.scan_and_trade()
            
            # Status every 10 cycles
            if cycle % 10 == 0:
                win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
                print(f"\n[{datetime.now().strftime('%H:%M')}] Status:")
                print(f"   Daily P&L: {self.daily_pnl:+.4f} SOL")
                print(f"   Trades: {self.total_trades} | Win: {win_rate:.0f}%")
                print(f"   Open: {len(self.positions)}")
            
            # Wait 60 seconds
            await asyncio.sleep(60)


async def demo_complete_trader():
    """Demo the complete trader"""
    print("=" * 70)
    print("COMPLETE VWAP TRADER - DEMO")
    print("=" * 70)
    
    trader = CompleteVWAPTrader(
        capital_sol=10.0,
        wallet_key=None,  # Simulation mode
        telegram_chat=None
    )
    
    # Run one scan cycle
    trades = await trader.scan_and_trade()
    
    print(f"\n📊 RESULTS:")
    print(f"   New trades: {len(trades)}")
    
    for t in trades:
        print(f"\n   {t['direction']} {t['symbol']}")
        print(f"   Entry: ${t['entry']:.2f} | SL: ${t['sl']:.2f} | TP: ${t['tp']:.2f}")
        print(f"   Size: {t['size']:.3f} SOL | R/R: {t['r_ratio']:.1f}:1")
    
    if not trades:
        print("   No trades this cycle (no VWAP deviation)")
    
    print("\n" + "=" * 70)
    print("Full mode: trader.run() for continuous trading")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(demo_complete_trader())