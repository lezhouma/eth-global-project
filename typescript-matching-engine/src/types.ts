export type Side = 'buy' | 'sell';

export interface Order {
  id:            string;
  side:          Side;
  price:         number;
  quantity:      number;
  userId:        string;
  walletAddress: string;
  timestamp:     Date;
}

export interface Trade {
  tradeId:       string;
  buyOrderId:    string;
  sellOrderId:   string;
  buyer:         string;
  buyerWallet:   string;
  seller:        string;
  sellerWallet:  string;
  price:         number;
  quantity:      number;
  notionalUsdc:  number;
}

export interface OrderInfo {
  orderId:         string;
  side:            Side;
  price:           number;
  quantity:        number;
  userId:          string;
  walletAddress:   string;
  timestamp:       string;
  remainingQuantity?: number;
}

export interface MatchResult {
  clearingPrice:   number | null;
  matchedQuantity: number;
  trades:          Trade[];
  unmatched:       OrderInfo[];
  message?:        string;
}

export interface SettlementLeg {
  wallet:     string;
  deltaToken: number;   // positive = received, negative = sent
  deltaUsdc:  number;   // positive = received, negative = sent
}

export interface AuctionResult extends MatchResult {
  auctionId:  string;
  closedAt:   string;
  settlement: {
    instructions:  SettlementLeg[];
    cantonResponse: unknown;
  } | null;
}
