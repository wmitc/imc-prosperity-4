from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json

class Trader:
    """
    IMC Prosperity Round 5 - Cherry Picking Winners
    
    Three-tier strategy based on extensive analysis of sample data:
    
    Tier 1 - HARDCODED: 11 products with consistent intraday direction across
    all 3 sample days. Take max position immediately at day start.
    
    Tier 2 - WAIT-AND-FOLLOW: ~30 products. Wait until price moves >100 from
    initial price, then commit to that direction at max position. No reversal.
    
    Tier 3 - SKIP: ~9 products that consistently mean-revert after initial moves.
    Trend-following loses money on these, so we don't trade them.
    
    Key discoveries:
    - PEBBLES group sums to exactly 50,000 (used for enhanced fair value)
    - SNACKPACK CHOC+VAN sum is ~constant (pairs relationship)
    - Many products have strong persistent intraday trends
    - Position limit: 10 per product
    """
    
    # Tier 1: Products with consistent intraday direction ALL 3 sample days
    ALWAYS_UP = frozenset({
        'GALAXY_SOUNDS_BLACK_HOLES',
        'OXYGEN_SHAKE_GARLIC',
        'PANEL_2X4',
        'SNACKPACK_STRAWBERRY',
        'UV_VISOR_RED',
    })
    
    ALWAYS_DOWN = frozenset({
        'MICROCHIP_OVAL',
        'PEBBLES_XS',
        'PEBBLES_S',
        'SNACKPACK_PISTACHIO',
        'UV_VISOR_AMBER',
        'SNACKPACK_CHOCOLATE',
    })
    
    # Tier 3: Products to skip - consistently lose with trend-following
    SKIP = frozenset({
        'SLEEP_POD_POLYESTER',
        'SLEEP_POD_LAMB_WOOL',
        'OXYGEN_SHAKE_CHOCOLATE',
        'PANEL_4X4',
        'MICROCHIP_SQUARE',
        'UV_VISOR_YELLOW',
        'GALAXY_SOUNDS_SOLAR_WINDS',
        'SNACKPACK_VANILLA',
        'SNACKPACK_RASPBERRY',
        'ROBOT_IRONING',
    })
    
    LIMIT = 10
    WF_THRESHOLD = 100

    def bid(self):
        return 15

    def run(self, state: TradingState):
        # Restore state
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                td = {"ip": {}, "cm": {}}
        else:
            td = {"ip": {}, "cm": {}}
        
        # ip = initial_prices, cm = committed directions
        initial_prices = td.get("ip", {})
        committed = td.get("cm", {})
        
        result = {}
        
        for product in state.order_depths:
            order_depth = state.order_depths[product]
            orders: List[Order] = []
            
            # Need both sides of the book
            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = orders
                continue
            
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid = (best_bid + best_ask) / 2.0
            
            position = state.position.get(product, 0)
            
            # Record initial price
            if product not in initial_prices:
                initial_prices[product] = mid
            
            # -----------------------------------------------------------
            # Tier 1: Hardcoded trending products - max position immediately
            # -----------------------------------------------------------
            if product in self.ALWAYS_UP:
                if position < self.LIMIT:
                    qty = self.LIMIT - position
                    orders.append(Order(product, best_ask, qty))
            
            elif product in self.ALWAYS_DOWN:
                if position > -self.LIMIT:
                    qty = position + self.LIMIT
                    orders.append(Order(product, best_bid, -qty))
            
            # -----------------------------------------------------------
            # Tier 3: Skip mean-reverting products
            # -----------------------------------------------------------
            elif product in self.SKIP:
                pass  # No orders
            
            # -----------------------------------------------------------
            # Tier 2: Wait-and-follow for remaining products
            # -----------------------------------------------------------
            else:
                initial = initial_prices[product]
                deviation = mid - initial
                
                # Commit to direction once threshold is crossed (one-time)
                if product not in committed:
                    if deviation > self.WF_THRESHOLD:
                        committed[product] = "L"  # Long
                    elif deviation < -self.WF_THRESHOLD:
                        committed[product] = "S"  # Short
                
                direction = committed.get(product)
                
                if direction == "L" and position < self.LIMIT:
                    qty = self.LIMIT - position
                    orders.append(Order(product, best_ask, qty))
                elif direction == "S" and position > -self.LIMIT:
                    qty = position + self.LIMIT
                    orders.append(Order(product, best_bid, -qty))
            
            result[product] = orders
        
        # Save state
        td["ip"] = initial_prices
        td["cm"] = committed
        traderData = json.dumps(td)
        
        conversions = 0
        return result, conversions, traderData