import { v4 as uuidv4 } from 'uuid';
import { Order, AuctionResult } from './types';
import { findClearingPrice } from './matching';
import { submitSettlement } from './settlement';

interface AuctionState {
  orders:  Order[];
  endTime: Date | null;
  isOpen:  boolean;
  result:  AuctionResult | null;
  timer:   NodeJS.Timeout | null;
}

const state: AuctionState = {
  orders:  [],
  endTime: null,
  isOpen:  false,
  result:  null,
  timer:   null,
};

export function startAuction(durationMinutes: number): Date {
  if (state.isOpen) throw new Error('Auction already running');

  state.orders  = [];
  state.result  = null;
  state.isOpen  = true;
  state.endTime = new Date(Date.now() + durationMinutes * 60_000);

  if (state.timer) clearTimeout(state.timer);
  state.timer = setTimeout(runUncross, durationMinutes * 60_000);

  return state.endTime;
}

export function addOrder(
  side:          Order['side'],
  price:         number,
  quantity:      number,
  userId:        string,
  walletAddress: string,
): string {
  if (!state.isOpen)             throw new Error('No auction is currently open');
  if (Date.now() >= state.endTime!.getTime()) throw new Error('Auction window has closed');

  const order: Order = {
    id:            uuidv4(),
    side,
    price,
    quantity,
    userId,
    walletAddress,
    timestamp:     new Date(),
  };
  state.orders.push(order);
  return order.id;
}

export function getStatus() {
  const secondsRemaining = state.endTime
    ? Math.max(0, (state.endTime.getTime() - Date.now()) / 1000)
    : 0;

  return {
    status:           state.isOpen ? 'open' : (state.endTime ? 'closed' : 'idle'),
    endTime:          state.endTime?.toISOString() ?? null,
    secondsRemaining: Math.round(secondsRemaining * 10) / 10,
    orderCount:       state.orders.length,
    buyOrders:  [...state.orders].filter(o => o.side === 'buy' ).sort((a, b) => b.price - a.price),
    sellOrders: [...state.orders].filter(o => o.side === 'sell').sort((a, b) => a.price - b.price),
  };
}

export function getResult(): AuctionResult | null {
  return state.result;
}

export function isOpen(): boolean {
  return state.isOpen;
}

async function runUncross(): Promise<void> {
  state.isOpen = false;
  const orders    = [...state.orders];
  const auctionId = uuidv4();

  const matchResult = findClearingPrice(orders);

  let settlement: AuctionResult['settlement'] = null;
  if (matchResult.trades.length > 0) {
    try {
      settlement = await submitSettlement(auctionId, matchResult.trades);
    } catch (err) {
      console.error('[UNCROSS] Settlement submission failed:', err);
      settlement = { instructions: [], cantonResponse: { error: String(err) } };
    }
  }

  state.result = {
    ...matchResult,
    auctionId,
    closedAt:  new Date().toISOString(),
    settlement,
  };

  console.log(
    `\n[UNCROSS] auctionId=${auctionId}  ` +
    `clearingPrice=${matchResult.clearingPrice}  ` +
    `matchedQty=${matchResult.matchedQuantity}  ` +
    `trades=${matchResult.trades.length}`,
  );
}
