from datamodel import OrderDepth, TradingState, Order
import json

class Trader:
    """
    Round 1 v3 — Confirmed limits 80 from wiki.

    INTARIAN_PEPPER_ROOT — "quite steady" (like EMERALDS)
        FV = day_base + 0.001 * t, residual std ~2.4
        Strategy: max long 80 all day, mark-to-market provides P&L
        Expected: ~80 × 92 pts ≈ 7,360 XIREC/day

    ASH_COATED_OSMIUM — "volatile with hidden pattern"
        FV ~10,000. Pattern: strong mean-reversion (lag-1 autocorr = -0.49).
        Market spread ~16 (bid ~9993, ask ~10009).
        Strategy: quote inside spread with inventory skew.
        Aggressive take on clear mispricings (ask < FV-2 or bid > FV+2).
    """

    LIMITS = {"INTARIAN_PEPPER_ROOT": 80, "ASH_COATED_OSMIUM": 80}

    # PEPPER
    P_SWEEP_BUF  = 20   # sweep asks up to FV + this (wide to capture all visible levels)
    P_PASSIVE_BUF = 2   # post passive bid at FV - this

    # OSMIUM
    O_FV       = 10_000
    O_SKEW     = 0#.10   # price skew per unit; capped at O_SKEW_CAP
    O_SKEW_CAP = 10     # maximum skew magnitude
    O_TAKE     = 2      # aggressively take when ask/bid within this of FV

    def __init__(self):
        self.pepper_base: float | None = None

    def run(self, state: TradingState):
        result = {}
        if state.traderData:
            try:
                self.pepper_base = json.loads(state.traderData).get("pb")
            except Exception:
                pass

        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            lim = self.LIMITS.get(product, 20)
            if product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._pepper(state.timestamp, od, pos, lim)
            elif product == "ASH_COATED_OSMIUM":
                result[product] = self._osmium(od, pos, lim)
            else:
                result[product] = []

        return result, 0, json.dumps({"pb": self.pepper_base})

    # ------------------------------------------------------------------ #
    #  PEPPER                                                              #
    # ------------------------------------------------------------------ #

    def _pepper_fv(self, ts: int, od: OrderDepth) -> float | None:
        bb = max(od.buy_orders)  if od.buy_orders  else None
        ba = min(od.sell_orders) if od.sell_orders else None
        if bb and ba:
            mid = (bb + ba) / 2.0
        elif bb:
            mid = float(bb)
        elif ba:
            mid = float(ba)
        else:
            return None
        obs = mid - 0.001 * ts
        self.pepper_base = obs if self.pepper_base is None else 0.97 * self.pepper_base + 0.03 * obs
        return self.pepper_base + 0.001 * ts

    def _pepper(self, ts: int, od: OrderDepth, pos: int, lim: int) -> list[Order]:
        orders: list[Order] = []
        fv = self._pepper_fv(ts, od)
        if fv is None:
            return orders

        want = lim - pos          # always target max long

        if want <= 0:
            return orders

        # Sweep all visible ask levels within FV + buffer
        for px in sorted(od.sell_orders):
            if px > fv + self.P_SWEEP_BUF:
                break
            vol = min(want, abs(od.sell_orders[px]))
            if vol > 0:
                orders.append(Order("INTARIAN_PEPPER_ROOT", px, vol))
                want -= vol
            if want <= 0:
                break

        # Passive bid just below FV to attract remaining sellers
        if want > 0:
            pbid = int(fv - self.P_PASSIVE_BUF)
            ba = min(od.sell_orders) if od.sell_orders else None
            if ba is None or pbid < ba:
                orders.append(Order("INTARIAN_PEPPER_ROOT", pbid, want))

        return orders

    # ------------------------------------------------------------------ #
    #  OSMIUM                                                              #
    # ------------------------------------------------------------------ #

    def _osmium(self, od: OrderDepth, pos: int, lim: int) -> list[Order]:
        orders: list[Order] = []
        fv = self.O_FV
        bb = max(od.buy_orders)  if od.buy_orders  else None
        ba = min(od.sell_orders) if od.sell_orders else None
        cur = pos

        # Aggressive mean-reversion takes (mispricings close to FV)
        if ba is not None and ba <= fv - self.O_TAKE and cur < lim:
            vol = min(abs(od.sell_orders[ba]), lim - cur)
            if vol > 0:
                orders.append(Order("ASH_COATED_OSMIUM", ba, vol))
                cur += vol

        if bb is not None and bb >= fv + self.O_TAKE and cur > -lim:
            vol = min(abs(od.buy_orders[bb]), lim + cur)
            if vol > 0:
                orders.append(Order("ASH_COATED_OSMIUM", bb, -vol))
                cur -= vol

        # Inside-spread passive quotes with inventory skew
        raw_skew = self.O_SKEW * cur
        skew = max(-self.O_SKEW_CAP, min(self.O_SKEW_CAP, raw_skew))

        if bb is not None and ba is not None:
            bid_px = bb + 1
            ask_px = ba - 1
            if bid_px >= ask_px:
                bid_px, ask_px = bb, ba
        elif bb is not None:
            bid_px, ask_px = bb, bb + 16
        elif ba is not None:
            bid_px, ask_px = ba - 16, ba
        else:
            bid_px, ask_px = fv - 8, fv + 8

        bid_px = int(bid_px - skew)
        ask_px = int(ask_px - skew)

        # Never let quotes cross fair value by more than 2
        bid_px = min(bid_px, fv + 2)
        ask_px = max(ask_px, fv - 2)
        if bid_px >= ask_px:
            bid_px = ask_px - 1

        buy_cap  = max(0, lim - cur)
        sell_cap = max(0, lim + cur)

        # Hard fence near limits — only quote the reducing direction
        if cur >= lim - 3:
            buy_cap = 0
        if cur <= -(lim - 3):
            sell_cap = 0

        if buy_cap  > 0:
            orders.append(Order("ASH_COATED_OSMIUM", bid_px,  buy_cap))
        if sell_cap > 0:
            orders.append(Order("ASH_COATED_OSMIUM", ask_px, -sell_cap))

        return orders