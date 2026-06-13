import { Trade, SettlementLeg } from './types';
import { submitToCantonJsonApi } from './canton';

/**
 * Net all trades into per-wallet positions, then submit to Canton.
 *
 * Each trade contributes two legs:
 *   buyer_wallet  : +quantity token,  -(quantity * price) USDC
 *   seller_wallet : -quantity token,  +(quantity * price) USDC
 */
export function buildSettlementInstructions(trades: Trade[]): SettlementLeg[] {
  const wallets = new Map<string, { deltaToken: number; deltaUsdc: number }>();

  for (const trade of trades) {
    const notional = trade.quantity * trade.price;

    const apply = (wallet: string, deltaToken: number, deltaUsdc: number) => {
      const pos = wallets.get(wallet) ?? { deltaToken: 0, deltaUsdc: 0 };
      wallets.set(wallet, {
        deltaToken: pos.deltaToken + deltaToken,
        deltaUsdc:  pos.deltaUsdc  + deltaUsdc,
      });
    };

    apply(trade.buyerWallet,  +trade.quantity, -notional);
    apply(trade.sellerWallet, -trade.quantity, +notional);
  }

  return Array.from(wallets.entries()).map(([wallet, pos]) => ({
    wallet,
    deltaToken: pos.deltaToken,
    deltaUsdc:  pos.deltaUsdc,
  }));
}

export async function submitSettlement(
  auctionId:    string,
  trades:       Trade[],
): Promise<{ instructions: SettlementLeg[]; cantonResponse: unknown }> {
  const instructions = buildSettlementInstructions(trades);
  const cantonResponse = await submitToCantonJsonApi(auctionId, instructions);
  return { instructions, cantonResponse };
}
