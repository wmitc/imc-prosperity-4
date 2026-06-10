"""
IMC Prosperity 4 - Round 3 Trading Algorithm
=============================================

Products & strategies:
  - HYDROGEL_PACK:        delta-1, fair tracked online via microprice +
                          slow EMA. Wide bot spread (~16 ticks). Adaptive
                          MM that scales edges to live half-spread, with
                          hard inventory cap.
  - VELVETFRUIT_EXTRACT:  delta-1, fair near 5250. Tight EMA + take.
  - VEV_4000 / VEV_4500:  deep ITM. Mid sticks tightly to S - K. MM tight
                          inside the wide bot book.
  - VEV_5000 - VEV_5500:  Black-Scholes fair value with per-strike IV
                          calibrated from historical fits.
  - VEV_6000 / VEV_6500:  no edge (mid stuck at 0.5). Skip.
"""

import json
import math
from typing import List
from datamodel import Order, OrderDepth, TradingState, Symbol


# ===========================================================
#  Constants
# ===========================================================
POSITION_LIMITS = {
    "HYDROGEL_PACK":       200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300, "VEV_4500": 300,
    "VEV_5000": 300, "VEV_5100": 300, "VEV_5200": 300,
    "VEV_5300": 300, "VEV_5400": 300, "VEV_5500": 300,
    "VEV_6000": 300, "VEV_6500": 300,
}
VEV_STRIKES = {
    "VEV_4000": 4000, "VEV_4500": 4500,
    "VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200,
    "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500,
    "VEV_6000": 6000, "VEV_6500": 6500,
}
DEEP_ITM_VOUCHERS = ["VEV_4000", "VEV_4500"]
BS_VOUCHERS       = ["VEV_5000", "VEV_5100", "VEV_5200",
                     "VEV_5300", "VEV_5400", "VEV_5500"]
SKIP_VOUCHERS     = ["VEV_6000", "VEV_6500"]

# Per-strike IV (calibrated). Smile is mostly flat ~1.27%/day with small skew.
PER_STRIKE_IV = {
    5000: 0.01270,
    5100: 0.01250,
    5200: 0.01270,
    5300: 0.01290,
    5400: 0.01200,
    5500: 0.01300,
}

# Round 3 starts with TTE = 5 days
ROUND_START_TTE_DAYS = 5.0
TS_PER_DAY = 1_000_000

# Backtest hook
TTE_OVERRIDE = None


# ===========================================================
#  HYDROGEL_PACK strategy parameters (new, replacing the old)
# ===========================================================
# Tuned via grid search over 3 days x 2 windows of historical data.
# Strategy: dynamic fair value from microprice (volume-weighted L1 mid),
# adaptive edges scaled to current half-spread, inventory skew, hard cap.
# No hardcoded fair value -- the price walks within a session, so any
# fixed level becomes a directional bet on mean reversion that does not
# happen on the timescale of one session.
HG_MAKE_FACTOR    = 0.48   # passive quote edge as a fraction of full spread
HG_TAKE_FACTOR    = 0.5    # take threshold as a fraction of half-spread
HG_INV_SKEW       = 0.02   # ticks of fair-value shift per unit of position
HG_SOFT_CAP       = 120    # |position| above which we stop quoting bad side
HG_MAX_QUOTE_SIZE = 20


# ===========================================================
#  Black-Scholes utilities (no scipy)
# ===========================================================
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S, K, T, sigma):
    if T <= 1e-9 or sigma <= 1e-9 or S <= 0:
        return max(S - K, 0.0)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * norm_cdf(d1) - K * norm_cdf(d2)


# ===========================================================
#  Trader
# ===========================================================
class Trader:

    def run(self, state: TradingState):
        memory = self._load_memory(state.traderData)
        result = {}
        positions = state.position

        S = self._mid_or_default(state, "VELVETFRUIT_EXTRACT", default=5250.0)

        # ----- HYDROGEL_PACK (new microprice strategy) -----
        result["HYDROGEL_PACK"] = self._hydrogel_strategy(
            state, positions.get("HYDROGEL_PACK", 0))

        # ----- VELVETFRUIT_EXTRACT (proven EMA/anchor strategy) -----
        result["VELVETFRUIT_EXTRACT"] = self._mm_strategy(
            symbol="VELVETFRUIT_EXTRACT", state=state,
            position=positions.get("VELVETFRUIT_EXTRACT", 0), memory=memory,
            anchor_fair=5250.0, ema_alpha=0.05,
            take_edge=2.0, make_offset=1,
            max_post=20, soft_limit_frac=0.7,
        )

        # ----- Voucher products -----
        tte_start = TTE_OVERRIDE if TTE_OVERRIDE is not None else ROUND_START_TTE_DAYS
        T = max(tte_start - state.timestamp / TS_PER_DAY, 1e-4)

        for sym in DEEP_ITM_VOUCHERS:
            result[sym] = self._intrinsic_arb(sym, state, positions.get(sym, 0), S)

        for sym in BS_VOUCHERS:
            result[sym] = self._bs_voucher(sym, state, positions.get(sym, 0), S, T)

        for sym in SKIP_VOUCHERS:
            result[sym] = []

        traderData = self._save_memory(memory)
        return result, 0, traderData

    # -------- Memory --------
    @staticmethod
    def _load_memory(raw):
        if not raw:
            return {"fair": {}}
        try:
            return json.loads(raw)
        except Exception:
            return {"fair": {}}

    @staticmethod
    def _save_memory(memory):
        try:
            return json.dumps(memory, separators=(",", ":"))
        except Exception:
            return ""

    # -------- Book helpers --------
    @staticmethod
    def _best_quotes(depth):
        bb = max(depth.buy_orders.keys())  if depth.buy_orders  else None
        ba = min(depth.sell_orders.keys()) if depth.sell_orders else None
        bv = depth.buy_orders[bb]          if bb is not None    else 0
        av = -depth.sell_orders[ba]        if ba is not None    else 0
        return bb, ba, bv, av

    def _mid_or_default(self, state, symbol, default=0.0):
        d = state.order_depths.get(symbol)
        if d is None:
            return default
        bb, ba, _, _ = self._best_quotes(d)
        if bb is None or ba is None:
            return default
        return (bb + ba) / 2.0

    # ===========================================================
    #  HYDROGEL_PACK strategy (NEW: microprice + adaptive edges)
    # ===========================================================
    def _hydrogel_strategy(self, state, position):
        symbol = "HYDROGEL_PACK"
        depth = state.order_depths.get(symbol)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return []

        bb, ba, bv, av = self._best_quotes(depth)
        if bb is None or ba is None:
            return []

        # Microprice: volume-weighted mid. Leans toward the side with less
        # touch volume (which empirically predicts the next move). When the
        # ask is thin, microprice tilts up because asks will get exhausted
        # first and price will rise.
        if bv > 0 and av > 0:
            fv = (av * bb + bv * ba) / (bv + av)
        else:
            fv = (bb + ba) / 2.0

        half_spread = (ba - bb) / 2.0
        limit = POSITION_LIMITS[symbol]
        orders = []
        buy_capacity = limit - position
        sell_capacity = limit + position

        # ---- 1. TAKE clearly mispriced quotes ----
        take_thresh = HG_TAKE_FACTOR * half_spread
        for ask in sorted(depth.sell_orders.keys()):
            if buy_capacity <= 0:
                break
            if ask >= fv - take_thresh:
                break
            qty = min(-depth.sell_orders[ask], buy_capacity)
            if qty > 0:
                orders.append(Order(symbol, int(ask), int(qty)))
                buy_capacity -= qty
                position += qty

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if sell_capacity <= 0:
                break
            if bid <= fv + take_thresh:
                break
            qty = min(depth.buy_orders[bid], sell_capacity)
            if qty > 0:
                orders.append(Order(symbol, int(bid), -int(qty)))
                sell_capacity -= qty
                position -= qty

        # ---- 2. MAKE: post inside the L1 spread with inventory skew ----
        skew = HG_INV_SKEW * position
        center = fv - skew
        edge = HG_MAKE_FACTOR * half_spread * 2
        if edge < 1.0:
            edge = 1.0

        passive_bid = int(math.floor(center - edge))
        passive_ask = int(math.ceil(center + edge))

        # Force quotes to sit strictly inside the live book (this is the
        # pattern from the proven _mm_strategy below).
        passive_bid = min(passive_bid, ba - 1)
        passive_ask = max(passive_ask, bb + 1)
        if passive_bid <= bb:
            passive_bid = bb + 1
        if passive_ask >= ba:
            passive_ask = ba - 1
        if passive_bid >= passive_ask:
            # Spread too tight to fit a quote on each side. Pick whichever
            # side reduces inventory.
            if position > 0:
                passive_bid = passive_ask - 1
            else:
                passive_ask = passive_bid + 1

        # ---- 3. Sizes with inventory cap ----
        bid_size = min(buy_capacity, HG_MAX_QUOTE_SIZE)
        ask_size = min(sell_capacity, HG_MAX_QUOTE_SIZE)

        if position > HG_SOFT_CAP:
            bid_size = 0
        elif position < -HG_SOFT_CAP:
            ask_size = 0

        if 0 < position <= HG_SOFT_CAP:
            scale = 1 - position / HG_SOFT_CAP
            bid_size = int(bid_size * scale)
        elif -HG_SOFT_CAP <= position < 0:
            scale = 1 - (-position) / HG_SOFT_CAP
            ask_size = int(ask_size * scale)

        # Now passive_bid is strictly in (bb, ba), passive_ask is strictly
        # in (bb, ba), and passive_bid < passive_ask. Safe to send.
        if bid_size > 0 and passive_bid > bb and passive_bid < ba:
            orders.append(Order(symbol, int(passive_bid), int(bid_size)))
        if ask_size > 0 and passive_ask > bb and passive_ask < ba:
            orders.append(Order(symbol, int(passive_ask), -int(ask_size)))

        return orders

    # ===========================================================
    #  Generic delta-1 MM (used by VELVETFRUIT_EXTRACT)
    # ===========================================================
    def _mm_strategy(self, symbol, state, position, memory,
                     anchor_fair, ema_alpha, take_edge,
                     make_offset, max_post, soft_limit_frac):
        depth = state.order_depths.get(symbol)
        if depth is None or (not depth.buy_orders and not depth.sell_orders):
            return []

        bb, ba, _, _ = self._best_quotes(depth)
        if bb is None or ba is None:
            return []

        mid = (bb + ba) / 2.0
        prev_fair = memory["fair"].get(symbol)
        if prev_fair is None:
            new_fair = mid
        else:
            new_fair = (1 - ema_alpha) * prev_fair + ema_alpha * mid
        # Anchor pull (resists trend chasing)
        new_fair = 0.995 * new_fair + 0.005 * anchor_fair
        memory["fair"][symbol] = new_fair
        fair = new_fair

        limit = POSITION_LIMITS[symbol]
        orders = []
        buy_capacity = limit - position
        sell_capacity = limit + position

        # ---- TAKE ----
        for ask in sorted(depth.sell_orders.keys()):
            if buy_capacity <= 0:
                break
            if ask <= fair - take_edge:
                qty = min(-depth.sell_orders[ask], buy_capacity)
                if qty > 0:
                    orders.append(Order(symbol, int(ask), int(qty)))
                    buy_capacity -= qty
                    position += qty
            else:
                break

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if sell_capacity <= 0:
                break
            if bid >= fair + take_edge:
                qty = min(depth.buy_orders[bid], sell_capacity)
                if qty > 0:
                    orders.append(Order(symbol, int(bid), -int(qty)))
                    sell_capacity -= qty
                    position -= qty
            else:
                break

        # ---- MAKE ----
        soft_lim = soft_limit_frac * limit
        inv_frac = position / limit
        if ba - bb >= 2:
            skew = -inv_frac * make_offset * 1.5
            quote_mid = fair + skew
            passive_bid = int(math.floor(quote_mid - make_offset))
            passive_ask = int(math.ceil(quote_mid + make_offset))
            passive_bid = min(passive_bid, ba - 1)
            passive_ask = max(passive_ask, bb + 1)
            if passive_bid <= bb:
                passive_bid = bb + 1
            if passive_ask >= ba:
                passive_ask = ba - 1

            buy_cap = max_post
            sell_cap = max_post
            if position > soft_lim:
                buy_cap = 0
                sell_cap = max_post * 2
            elif position < -soft_lim:
                buy_cap = max_post * 2
                sell_cap = 0

            if passive_bid < ba and passive_bid > bb and buy_capacity > 0 and buy_cap > 0:
                size = min(buy_capacity, buy_cap)
                orders.append(Order(symbol, int(passive_bid), int(size)))
            if passive_ask > bb and passive_ask < ba and sell_capacity > 0 and sell_cap > 0:
                size = min(sell_capacity, sell_cap)
                orders.append(Order(symbol, int(passive_ask), -int(size)))

        return orders

    # ===========================================================
    #  Deep-ITM intrinsic arb (VEV_4000, VEV_4500)
    # ===========================================================
    def _intrinsic_arb(self, symbol, state, position, S):
        depth = state.order_depths.get(symbol)
        if depth is None:
            return []
        K = VEV_STRIKES[symbol]
        intrinsic = max(S - K, 0.0)
        limit = POSITION_LIMITS[symbol]
        orders = []
        buy_capacity = limit - position
        sell_capacity = limit + position

        # ---- TAKE ----
        for ask in sorted(depth.sell_orders.keys()):
            if buy_capacity <= 0:
                break
            if ask <= intrinsic - 2:
                qty = min(-depth.sell_orders[ask], buy_capacity)
                if qty > 0:
                    orders.append(Order(symbol, int(ask), int(qty)))
                    buy_capacity -= qty
                    position += qty
            else:
                break

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if sell_capacity <= 0:
                break
            if bid >= intrinsic + 2:
                qty = min(depth.buy_orders[bid], sell_capacity)
                if qty > 0:
                    orders.append(Order(symbol, int(bid), -int(qty)))
                    sell_capacity -= qty
                    position -= qty
            else:
                break

        # ---- MAKE inside the wide spread ----
        bb, ba, _, _ = self._best_quotes(depth)
        if bb is not None and ba is not None and ba - bb >= 4:
            inv_frac = position / limit
            quote_mid = intrinsic - inv_frac * 1.0
            passive_bid = int(math.floor(quote_mid - 1))
            passive_ask = int(math.ceil(quote_mid + 1))
            passive_bid = min(passive_bid, ba - 1)
            passive_ask = max(passive_ask, bb + 1)
            if passive_bid <= bb:
                passive_bid = bb + 1
            if passive_ask >= ba:
                passive_ask = ba - 1

            buy_cap = 25
            sell_cap = 25
            soft_lim = 0.7 * limit
            if position > soft_lim:
                buy_cap = 0
            if position < -soft_lim:
                sell_cap = 0

            if passive_bid < ba and passive_bid > bb and buy_capacity > 0 and buy_cap > 0:
                size = min(buy_capacity, buy_cap)
                orders.append(Order(symbol, int(passive_bid), int(size)))
            if passive_ask > bb and passive_ask < ba and sell_capacity > 0 and sell_cap > 0:
                size = min(sell_capacity, sell_cap)
                orders.append(Order(symbol, int(passive_ask), -int(size)))

        return orders

    # ===========================================================
    #  BS-priced voucher (VEV_5000-VEV_5500)
    # ===========================================================
    def _bs_voucher(self, symbol, state, position, S, T):
        depth = state.order_depths.get(symbol)
        if depth is None or (not depth.buy_orders and not depth.sell_orders):
            return []

        K = VEV_STRIKES[symbol]
        sigma = PER_STRIKE_IV.get(K, 0.0127)
        fair = bs_call(S, K, T, sigma)

        limit = POSITION_LIMITS[symbol]
        orders = []
        buy_capacity = limit - position
        sell_capacity = limit + position

        edge_take = max(3.0, min(6.0, 0.07 * max(fair, 1.0)))
        edge_make = max(2.0, min(4.0, 0.04 * max(fair, 1.0)))

        # ---- TAKE ----
        for ask in sorted(depth.sell_orders.keys()):
            if buy_capacity <= 0:
                break
            if ask <= fair - edge_take:
                qty = min(-depth.sell_orders[ask], buy_capacity)
                if qty > 0:
                    orders.append(Order(symbol, int(ask), int(qty)))
                    buy_capacity -= qty
                    position += qty
            else:
                break

        for bid in sorted(depth.buy_orders.keys(), reverse=True):
            if sell_capacity <= 0:
                break
            if bid >= fair + edge_take:
                qty = min(depth.buy_orders[bid], sell_capacity)
                if qty > 0:
                    orders.append(Order(symbol, int(bid), -int(qty)))
                    sell_capacity -= qty
                    position -= qty
            else:
                break

        # ---- MAKE ----
        bb, ba, _, _ = self._best_quotes(depth)
        if bb is not None and ba is not None and (ba - bb) >= 2:
            inv_frac = position / limit
            quote_mid = fair - inv_frac * edge_make * 1.2
            passive_bid = int(math.floor(quote_mid - edge_make))
            passive_ask = int(math.ceil(quote_mid + edge_make))
            passive_bid = min(passive_bid, ba - 1)
            passive_ask = max(passive_ask, bb + 1)
            if passive_bid <= bb:
                passive_bid = bb + 1
            if passive_ask >= ba:
                passive_ask = ba - 1

            max_post = 10
            buy_cap = max_post
            sell_cap = max_post
            soft_lim = 0.5 * limit
            if position > soft_lim:
                buy_cap = 0
                sell_cap = max_post * 2
            elif position < -soft_lim:
                buy_cap = max_post * 2
                sell_cap = 0

            if passive_bid < ba and passive_bid > bb and buy_capacity > 0 and buy_cap > 0:
                size = min(buy_capacity, buy_cap)
                orders.append(Order(symbol, int(passive_bid), int(size)))
            if passive_ask > bb and passive_ask < ba and sell_capacity > 0 and sell_cap > 0:
                size = min(sell_capacity, sell_cap)
                orders.append(Order(symbol, int(passive_ask), -int(size)))

        return orders