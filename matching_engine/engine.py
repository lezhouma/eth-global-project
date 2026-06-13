"""
Call Auction Matching Engine
----------------------------
Runs a batch auction for X minutes. Users submit limit orders via REST API.
At close, "uncrosses" at the single clearing price that maximises matched volume,
then emits settlement instructions to Canton via settlement.py.

Endpoints
---------
POST /auction/start   { "duration_minutes": 5 }
POST /orders          { "side": "buy"|"sell", "price": 100.5, "quantity": 10,
                        "user_id": "alice", "wallet_address": "0xABC..." }
GET  /auction/status  live order book snapshot + time remaining
GET  /auction/result  clearing price, trades, settlement (available after close)
"""

from flask import Flask, request, jsonify
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import threading
import uuid

from settlement import build_settlement_instructions, submit_settlement

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Order:
    id:             str
    side:           str       # "buy" | "sell"
    price:          float
    quantity:       float
    user_id:        str
    wallet_address: str
    timestamp:      datetime


@dataclass
class AuctionState:
    orders:   list                  = field(default_factory=list)
    end_time: Optional[datetime]    = None
    is_open:  bool                  = False
    result:   Optional[dict]        = None
    lock:     threading.Lock        = field(default_factory=threading.Lock)
    _timer:   Optional[threading.Timer] = field(default=None, repr=False)


auction = AuctionState()


# ---------------------------------------------------------------------------
# Clearing price algorithm
# ---------------------------------------------------------------------------

def find_clearing_price(orders: list) -> dict:
    """
    Find the price that maximises executable volume, then apply the marginal
    order convention to select a single clearing price from the flat region:

      - Excess buys  (demand > supply) → clearing = top of flat range
                                          (marginal buyer's price, like a Treasury
                                           stop-out — the lowest accepted bid wins)
      - Excess sells (supply > demand) → clearing = bottom of flat range
                                          (marginal seller's price — highest
                                           accepted ask wins)
      - Balanced                       → midpoint of the flat range
    """
    buys  = [o for o in orders if o.side == "buy"]
    sells = [o for o in orders if o.side == "sell"]

    if not buys or not sells:
        return {"clearing_price": None, "matched_quantity": 0, "trades": [],
                "unmatched": [_order_dict(o) for o in orders],
                "message": "Insufficient orders on one side — no match."}

    candidates = sorted({o.price for o in orders})
    best_qty    = 0
    best_prices = []

    for p in candidates:
        buy_qty  = sum(o.quantity for o in buys  if o.price >= p)
        sell_qty = sum(o.quantity for o in sells if o.price <= p)
        exe = min(buy_qty, sell_qty)
        if exe > best_qty:
            best_qty    = exe
            best_prices = [p]
        elif exe == best_qty and exe > 0:
            best_prices.append(p)

    if best_qty == 0:
        return {"clearing_price": None, "matched_quantity": 0, "trades": [],
                "unmatched": [_order_dict(o) for o in orders],
                "message": "No crossing — best bid < best ask."}

    p_low, p_high = best_prices[0], best_prices[-1]
    buy_at_low  = sum(o.quantity for o in buys  if o.price >= p_low)
    sell_at_low = sum(o.quantity for o in sells if o.price <= p_low)

    if buy_at_low > sell_at_low:
        clearing_price = p_high                    # excess buys  → marginal buyer sets price
    elif sell_at_low > buy_at_low:
        clearing_price = p_low                     # excess sells → marginal seller sets price
    else:
        clearing_price = (p_low + p_high) / 2     # balanced     → midpoint

    trades, unmatched = _fill_at_price(buys, sells, clearing_price, best_qty)

    return {
        "clearing_price":  clearing_price,
        "matched_quantity": best_qty,
        "trades":          trades,
        "unmatched":       unmatched,
    }


def _fill_at_price(buys, sells, price, max_qty):
    """Match eligible orders at `price` up to `max_qty`, price-then-time priority."""
    eligible_buys  = sorted([o for o in buys  if o.price >= price],
                            key=lambda o: (-o.price, o.timestamp))
    eligible_sells = sorted([o for o in sells if o.price <= price],
                            key=lambda o: (o.price, o.timestamp))

    rem_b = {o.id: o.quantity for o in eligible_buys}
    rem_s = {o.id: o.quantity for o in eligible_sells}

    trades = []
    bi = si = filled = 0

    while bi < len(eligible_buys) and si < len(eligible_sells) and filled < max_qty:
        b = eligible_buys[bi]
        s = eligible_sells[si]
        qty = min(rem_b[b.id], rem_s[s.id], max_qty - filled)

        trades.append({
            "trade_id":       str(uuid.uuid4()),
            "buy_order_id":   b.id,
            "sell_order_id":  s.id,
            "buyer":          b.user_id,
            "buyer_wallet":   b.wallet_address,
            "seller":         s.user_id,
            "seller_wallet":  s.wallet_address,
            "price":          price,
            "quantity":       qty,
            "notional_usdc":  qty * price,
        })

        rem_b[b.id] -= qty
        rem_s[s.id] -= qty
        filled       += qty
        if rem_b[b.id] == 0:
            bi += 1
        if rem_s[s.id] == 0:
            si += 1

    unmatched = []
    for o in eligible_buys:
        if rem_b[o.id] > 0:
            d = _order_dict(o)
            d["remaining_quantity"] = rem_b[o.id]
            unmatched.append(d)
    for o in eligible_sells:
        if rem_s[o.id] > 0:
            d = _order_dict(o)
            d["remaining_quantity"] = rem_s[o.id]
            unmatched.append(d)

    return trades, unmatched


def _order_dict(o: Order) -> dict:
    return {
        "order_id":       o.id,
        "side":           o.side,
        "price":          o.price,
        "quantity":       o.quantity,
        "user_id":        o.user_id,
        "wallet_address": o.wallet_address,
        "timestamp":      o.timestamp.isoformat(),
    }


# ---------------------------------------------------------------------------
# Auction lifecycle
# ---------------------------------------------------------------------------

def _run_uncross():
    with auction.lock:
        auction.is_open = False
        orders = list(auction.orders)

    auction_id = str(uuid.uuid4())
    result = find_clearing_price(orders)
    result["closed_at"]  = datetime.now(timezone.utc).isoformat()
    result["auction_id"] = auction_id

    # Build per-wallet settlement instructions and submit to Canton
    if result["trades"]:
        instructions = build_settlement_instructions(result["trades"])
        canton_response = submit_settlement(instructions, auction_id)
        result["settlement"] = {
            "instructions": instructions,
            "canton_response": canton_response,
        }
    else:
        result["settlement"] = None

    with auction.lock:
        auction.result = result

    print(f"\n[UNCROSS] auction_id={auction_id}  "
          f"clearing_price={result['clearing_price']}  "
          f"matched_qty={result['matched_quantity']}  "
          f"trades={len(result['trades'])}")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/auction/start", methods=["POST"])
def start_auction():
    data     = request.get_json(force=True)
    duration = float(data.get("duration_minutes", 5))
    if duration <= 0:
        return jsonify({"error": "duration_minutes must be positive"}), 400

    with auction.lock:
        if auction.is_open:
            return jsonify({"error": "Auction already running"}), 409
        auction.orders   = []
        auction.result   = None
        auction.is_open  = True
        auction.end_time = datetime.now(timezone.utc) + timedelta(minutes=duration)
        if auction._timer:
            auction._timer.cancel()
        t = threading.Timer(duration * 60, _run_uncross)
        t.daemon = True
        t.start()
        auction._timer = t

    return jsonify({
        "status":           "started",
        "end_time":         auction.end_time.isoformat(),
        "duration_minutes": duration,
    })


@app.route("/orders", methods=["POST"])
def place_order():
    data = request.get_json(force=True)

    side           = data.get("side", "").lower()
    price          = data.get("price")
    quantity       = data.get("quantity")
    user_id        = data.get("user_id", "anonymous")
    wallet_address = data.get("wallet_address", "")

    if side not in ("buy", "sell"):
        return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
    if price is None or quantity is None:
        return jsonify({"error": "price and quantity are required"}), 400
    if float(price) <= 0 or float(quantity) <= 0:
        return jsonify({"error": "price and quantity must be positive"}), 400
    if not wallet_address:
        return jsonify({"error": "wallet_address is required"}), 400

    with auction.lock:
        if not auction.is_open:
            return jsonify({"error": "No auction is currently open"}), 409
        if datetime.now(timezone.utc) >= auction.end_time:
            return jsonify({"error": "Auction window has closed"}), 409

        order = Order(
            id             = str(uuid.uuid4()),
            side           = side,
            price          = float(price),
            quantity       = float(quantity),
            user_id        = user_id,
            wallet_address = wallet_address,
            timestamp      = datetime.now(timezone.utc),
        )
        auction.orders.append(order)

    return jsonify({"order_id": order.id, "status": "accepted"}), 201


@app.route("/auction/status", methods=["GET"])
def auction_status():
    with auction.lock:
        if not auction.is_open and auction.end_time is None:
            return jsonify({"status": "idle"})

        now       = datetime.now(timezone.utc)
        remaining = max(0.0, (auction.end_time - now).total_seconds()) if auction.end_time else 0

        buys  = sorted([_order_dict(o) for o in auction.orders if o.side == "buy"],
                       key=lambda x: -x["price"])
        sells = sorted([_order_dict(o) for o in auction.orders if o.side == "sell"],
                       key=lambda x: x["price"])

        return jsonify({
            "status":            "open" if auction.is_open else "closed",
            "end_time":          auction.end_time.isoformat() if auction.end_time else None,
            "seconds_remaining": round(remaining, 1),
            "order_count":       len(auction.orders),
            "buy_orders":        buys,
            "sell_orders":       sells,
        })


@app.route("/auction/result", methods=["GET"])
def auction_result():
    with auction.lock:
        if auction.is_open:
            return jsonify({"error": "Auction still open — check back after close"}), 425
        if auction.result is None:
            return jsonify({"error": "No auction result available yet"}), 404
        return jsonify(auction.result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Call Auction Engine — http://localhost:5050")
    print("  POST /auction/start   { duration_minutes }")
    print("  POST /orders          { side, price, quantity, user_id, wallet_address }")
    print("  GET  /auction/status")
    print("  GET  /auction/result\n")
    app.run(host="0.0.0.0", port=5050, debug=False)
