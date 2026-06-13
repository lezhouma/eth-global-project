import { v4 as uuidv4 } from 'uuid';
import { Order, Trade, MatchResult, OrderInfo } from './types';

export function findClearingPrice(orders: Order[]): MatchResult {
  const buys  = orders.filter(o => o.side === 'buy');
  const sells = orders.filter(o => o.side === 'sell');

  if (!buys.length || !sells.length) {
    return {
      clearingPrice: null, matchedQuantity: 0, trades: [],
      unmatched: orders.map(toOrderInfo),
      message: 'Insufficient orders on one side — no match.',
    };
  }

  // Collect every unique price across all orders as candidate clearing prices
  const candidates = [...new Set(orders.map(o => o.price))].sort((a, b) => a - b);

  let bestQty    = 0;
  let bestPrices: number[] = [];

  for (const p of candidates) {
    const buyQty  = buys .filter(o => o.price >= p).reduce((s, o) => s + o.quantity, 0);
    const sellQty = sells.filter(o => o.price <= p).reduce((s, o) => s + o.quantity, 0);
    const exe = Math.min(buyQty, sellQty);
    if (exe > bestQty) {
      bestQty    = exe;
      bestPrices = [p];
    } else if (exe === bestQty && exe > 0) {
      bestPrices.push(p);
    }
  }

  if (bestQty === 0) {
    return {
      clearingPrice: null, matchedQuantity: 0, trades: [],
      unmatched: orders.map(toOrderInfo),
      message: 'No crossing — best bid < best ask.',
    };
  }

  // Marginal order convention:
  //   excess buys  → scarce supply sets the level → use top of flat range (marginal buyer price)
  //   excess sells → scarce demand sets the level → use bottom of flat range (marginal seller price)
  //   balanced     → midpoint
  const pLow  = bestPrices[0];
  const pHigh = bestPrices[bestPrices.length - 1];
  const buyAtLow  = buys .filter(o => o.price >= pLow).reduce((s, o) => s + o.quantity, 0);
  const sellAtLow = sells.filter(o => o.price <= pLow).reduce((s, o) => s + o.quantity, 0);

  let clearingPrice: number;
  if (buyAtLow > sellAtLow)      clearingPrice = pHigh;
  else if (sellAtLow > buyAtLow) clearingPrice = pLow;
  else                           clearingPrice = (pLow + pHigh) / 2;

  const { trades, unmatched } = fillAtPrice(buys, sells, clearingPrice, bestQty);
  return { clearingPrice, matchedQuantity: bestQty, trades, unmatched };
}

function fillAtPrice(
  buys: Order[],
  sells: Order[],
  price: number,
  maxQty: number,
): { trades: Trade[]; unmatched: OrderInfo[] } {
  const eligibleBuys  = buys .filter(o => o.price >= price)
    .sort((a, b) => b.price - a.price || a.timestamp.getTime() - b.timestamp.getTime());
  const eligibleSells = sells.filter(o => o.price <= price)
    .sort((a, b) => a.price - b.price || a.timestamp.getTime() - b.timestamp.getTime());

  const remB: Record<string, number> = {};
  const remS: Record<string, number> = {};
  eligibleBuys .forEach(o => { remB[o.id] = o.quantity; });
  eligibleSells.forEach(o => { remS[o.id] = o.quantity; });

  const trades: Trade[] = [];
  let bi = 0, si = 0, filled = 0;

  while (bi < eligibleBuys.length && si < eligibleSells.length && filled < maxQty) {
    const b   = eligibleBuys[bi];
    const s   = eligibleSells[si];
    const qty = Math.min(remB[b.id], remS[s.id], maxQty - filled);

    trades.push({
      tradeId:      uuidv4(),
      buyOrderId:   b.id,
      sellOrderId:  s.id,
      buyer:        b.userId,
      buyerWallet:  b.walletAddress,
      seller:       s.userId,
      sellerWallet: s.walletAddress,
      price,
      quantity:     qty,
      notionalUsdc: qty * price,
    });

    remB[b.id] -= qty;
    remS[s.id] -= qty;
    filled      += qty;
    if (remB[b.id] === 0) bi++;
    if (remS[s.id] === 0) si++;
  }

  const unmatched: OrderInfo[] = [];
  for (const o of eligibleBuys)  if (remB[o.id] > 0) unmatched.push({ ...toOrderInfo(o), remainingQuantity: remB[o.id] });
  for (const o of eligibleSells) if (remS[o.id] > 0) unmatched.push({ ...toOrderInfo(o), remainingQuantity: remS[o.id] });

  return { trades, unmatched };
}

function toOrderInfo(o: Order): OrderInfo {
  return {
    orderId:       o.id,
    side:          o.side,
    price:         o.price,
    quantity:      o.quantity,
    userId:        o.userId,
    walletAddress: o.walletAddress,
    timestamp:     o.timestamp.toISOString(),
  };
}
