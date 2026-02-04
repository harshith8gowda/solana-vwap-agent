#!/usr/bin/env python3
"""
Solana VWAP Trading Agent
Autonomous mean reversion trading on Solana DEXes
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests

class SolanaVWAPTrader:
    """
    VWAP mean reversion bot for Solana.
    
    Monitors Jupiter/Raydium, executes on VWAP deviation.
    """
    
    def __init__(self, capital_sol: float = 10.0):
        """
        Args:
            capital_sol: Capital in SOL (default 10 SOL ~ $2K)
        """
        self.capital_sol = capital_sol
        self.risk_per_trade = 0.01  # 1%
        
        # Jupiter API
        self.jupiter_api = "https://quote-api.jup.ag/v6"
        
        # Track positions
        self.positions: List[Dict] = []
        self.daily_pnl_sol = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        
        # Risk limits
        self.max_positions = 3
        self.daily_stop_pct = 0.05  # -5%
        self.min_r_ratio = 1.5
        
    async def get_price_data(self, token: str) -> Optional[Dict]:
        """
        Get price and recent trade data for VWAP calculation.
        
        Uses Jupiter price API + recent trade history.
        """
        try:
            # Get current price from Jupiter
            # Real endpoint: GET /price?id=tokenMint
            
            # Simulated for demo
            import random
            base_price = random.uniform(100, 200)  # Simulated token price
            
            # Generate recent trade data for VWAP
            trades = []
            for i in range(20):  # Last 20 trades
                price = base_price * (1 + random.uniform(-0.005, 0.005))
                size = random.uniform(0.1, 10.0)  # Trade size
                trades.append({'price': price, 'size': size})
            
            return {
                'current_price': base_price,
                'trades': trades,
                'token': token
            }
        except Exception as e:
            print(f"Price fetch error: {e}")
            return None
    
    def calculate_vwap(self, trades: List[Dict]) -> Tuple[float, float]:
        """
        Calculate VWAP from trade history.
        
        VWAP = Sum(price * volume) / Sum(volume)
        """
        if not trades:
            return 0.0, 0.0
        
        total_value = sum(t['price'] * t['size'] for t in trades)
        total_volume = sum(t['size'] for t in trades)
        
        vwap = total_value / total_volume if total_volume > 0 else 0
        
        # Calculate standard deviation for volatility
        prices = [t['price'] for t in trades]
        mean_price = sum(prices) / len(prices)
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5
        
        return vwap, std_dev
    
    def check_signal(self, current: float, vwap: float, std_dev: float) -> Optional[Dict]:
        """
        Check for mean reversion signal.
        
        Signal: Price extends beyond VWAP + threshold
        """
        # Distance from VWAP in percent
        distance_pct = ((current - vwap) / vwap) * 100
        
        # Dynamic threshold based on volatility (std_dev)
        # Require at least 0.5% or 1 std dev, whichever is larger
        threshold = max(0.5, (std_dev / vwap) * 100 * 1.5)
        
        # Check for extended price
        if abs(distance_pct) > threshold:
            # Mean reversion signal
            direction = "SHORT" if distance_pct > 0 else "LONG"
            
            # Calculate entry, SL, TP
            entry = current
            
            if direction == "LONG":
                # Long: SL below entry, TP toward VWAP + beyond
                sl = entry * 0.995  # 0.5% stop
                tp = vwap + (vwap - entry) * 0.5  # Revert past VWAP
            else:
                # Short: SL above entry, TP toward VWAP
                sl = entry * 1.005  # 0.5% stop
                tp = vwap - (entry - vwap) * 0.5
            
            # Check R/R ratio
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            r_ratio = reward / risk if risk > 0 else 0
            
            if r_ratio >= self.min_r_ratio:
                return {
                    'direction': direction,
                    'entry': entry,
                    'sl': sl,
                    'tp': tp,
                    'vwap': vwap,
                    'distance_pct': distance_pct,
                    'r_ratio': r_ratio,
                    'confidence': min(abs(distance_pct) * 10, 95)
                }
        
        return None
    
    async def execute_trade(self, signal: Dict, token: str) -> Dict:
        """
        Execute trade via Jupiter.
        
        In production: Build swap transaction, sign, send.
        """
        # Calculate position size (1% risk)
        risk_amount_sol = self.capital_sol * self.risk_per_trade
        
        # Position size based on stop distance
        sl_distance = abs(signal['entry'] - signal['sl'])
        position_value_sol = risk_amount_sol / (sl_distance / signal['entry'])
        
        # Cap at 20% of capital
        max_position = self.capital_sol * 0.20
        position_value_sol = min(position_value_sol, max_position)
        
        trade = {
            'id': f"SOL_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'token': token,
            'direction': signal['direction'],
            'entry_price': signal['entry'],
            'stop_loss': signal['sl'],
            'take_profit': signal['tp'],
            'position_size_sol': position_value_sol,
            'vwap': signal['vwap'],
            'r_ratio': signal['r_ratio'],
            'confidence': signal['confidence'],
            'entry_time': datetime.now().isoformat(),
            'status': 'OPEN',
            'tx_hash': None  # Would be filled after on-chain execution
        }
        
        self.positions.append(trade)
        self.total_trades += 1
        
        return {
            'success': True,
            'trade': trade,
            'message': f"Executed {signal['direction']} {token} at {signal['entry']:.4f}"
        }
    
    async def check_exits(self, current_prices: Dict):
        """Check if any positions hit SL or TP"""
        closed = []
        
        for pos in self.positions[:]:
            token = pos['token']
            if token not in current_prices:
                continue
            
            current = current_prices[token]
            direction = pos['direction']
            sl = pos['stop_loss']
            tp = pos['take_profit']
            
            # Check SL
            sl_hit = (direction == 'LONG' and current <= sl) or \
                     (direction == 'SHORT' and current >= sl)
            
            # Check TP
            tp_hit = (direction == 'LONG' and current >= tp) or \
                     (direction == 'SHORT' and current <= tp)
            
            if sl_hit or tp_hit:
                # Calculate P&L
                entry = pos['entry_price']
                size = pos['position_size_sol']
                
                if tp_hit:
                    pnl_pct = abs(tp - entry) / entry
                    pnl_sol = size * pnl_pct * 0.95  # After 0.5% Jupiter fee
                    result = 'WIN'
                    self.winning_trades += 1
                else:
                    pnl_pct = -abs(sl - entry) / entry
                    pnl_sol = size * pnl_pct
                    result = 'LOSS'
                
                self.daily_pnl_sol += pnl_sol
                
                pos['exit_price'] = current
                pos['exit_time'] = datetime.now().isoformat()
                pos['pnl_sol'] = pnl_sol
                pos['result'] = result
                pos['status'] = 'CLOSED'
                
                closed.append(pos)
                self.positions.remove(pos)
        
        return closed
    
    async def scan_and_trade(self):
        """Main scan cycle"""
        # Tokens to monitor (major Solana tokens)
        tokens = ['SOL', 'USDC', 'BONK', 'JUP']  # Would use mint addresses
        
        opportunities = []
        
        for token in tokens:
            # Skip if max positions reached
            if len(self.positions) >= self.max_positions:
                break
            
            # Get price data
            data = await self.get_price_data(token)
            if not data:
                continue
            
            # Calculate VWAP
            vwap, std_dev = self.calculate_vwap(data['trades'])
            
            # Check for signal
            signal = self.check_signal(data['current_price'], vwap, std_dev)
            
            if signal:
                # Execute trade
                result = await self.execute_trade(signal, token)
                if result['success']:
                    opportunities.append(result['trade'])
        
        return opportunities
    
    async def run(self):
        """Main trading loop"""
        print("=" * 70)
        print("SOLANA VWAP TRADING AGENT")
        print("=" * 70)
        print(f"Capital: {self.capital_sol:.2f} SOL")
        print(f"Risk: {self.risk_per_trade:.0%} per trade")
        print(f"Strategy: VWAP Mean Reversion")
        print("=" * 70)
        
        while True:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning...")
            
            # Check risk limits
            if self.daily_pnl_sol < -self.capital_sol * self.daily_stop_pct:
                print("❌ Daily stop loss hit. Pausing trading.")
                break
            
            # Scan and trade
            trades = await self.scan_and_trade()
            
            if trades:
                print(f"✅ Opened {len(trades)} positions:")
                for t in trades:
                    print(f"   {t['direction']} {t['token']} @ {t['entry_price']:.4f}")
            
            # Print status
            print(f"\n📊 Status:")
            print(f"   Balance: {self.capital_sol:.2f} SOL")
            print(f"   Daily P&L: {self.daily_pnl_sol:+.4f} SOL")
            print(f"   Open: {len(self.positions)} | Total: {self.total_trades}")
            if self.total_trades > 0:
                win_rate = (self.winning_trades / self.total_trades) * 100
                print(f"   Win Rate: {win_rate:.1f}%")
            
            # Wait next cycle
            await asyncio.sleep(60)  # 1 minute between scans

if __name__ == "__main__":
    print("=" * 70)
    print("SOLANA VWAP TRADING AGENT - DEMO MODE")
    print("=" * 70)
    print("\n⚠️  This is a simulation.")
    print("Real trading requires:")
    print("- Solana wallet with private key")
    print("- Jupiter API integration")
    print("- On-chain transaction signing")
    print("- Risk management safeguards")
    print("\nRunning simulation with 10 SOL capital...")
    print("=" * 70)
    
    trader = SolanaVWAPTrader(capital_sol=10.0)
    
    # Demo: Run single scan
    async def demo():
        trades = await trader.scan_and_trade()
        print(f"\nDemo complete. Trades: {len(trades)}")
        if trades:
            for t in trades:
                print(f"   {t['direction']} {t['token']}: Entry {t['entry_price']:.4f}")
    
    asyncio.run(demo())
    
    print("\n✅ Demo complete.")
    print("Real trading: Connect Solana wallet + Jupiter API")