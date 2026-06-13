/**
 * Canton Network — Settlement submission
 *
 * This module submits settlement instructions to a Daml contract on Canton via
 * the HTTP JSON API (no codegen required).
 *
 * When your teammate's contract is ready, swap to the @daml/ledger SDK approach
 * shown at the bottom of this file for full type-safety.
 *
 * Canton JSON API docs: https://docs.daml.com/json-api/
 * Ledger API endpoint:  POST /v1/exercise
 */

import { SettlementLeg } from './types';

const CANTON_URL    = process.env.CANTON_JSON_API_URL  ?? 'http://localhost:7575';
const AUTH_TOKEN    = process.env.CANTON_AUTH_TOKEN    ?? '';
const TEMPLATE_ID   = process.env.SETTLEMENT_TEMPLATE_ID  ?? 'Auction:AuctionSettlement';
const CONTRACT_ID   = process.env.SETTLEMENT_CONTRACT_ID  ?? '';
const CHOICE        = process.env.SETTLEMENT_CHOICE       ?? 'Settle';

// Shape of the Daml choice argument — align this with your teammate's Daml template:
//   choice Settle : ()
//     with
//       auctionId   : Text
//       settlements : [SettlementLeg]
//     controller appOperator
interface DamlSettlementLeg {
  wallet:     string;
  deltaToken: string;   // Daml Decimal must be sent as a string
  deltaUsdc:  string;
}

interface ExerciseRequest {
  templateId: string;
  contractId: string;
  choice:     string;
  argument: {
    auctionId:   string;
    settlements: DamlSettlementLeg[];
  };
}

export async function submitToCantonJsonApi(
  auctionId:    string,
  instructions: SettlementLeg[],
): Promise<unknown> {
  if (!CONTRACT_ID) {
    console.warn('[CANTON] SETTLEMENT_CONTRACT_ID not set — logging payload only.');
    const payload = buildPayload(auctionId, instructions);
    console.log('[CANTON] Would POST:', JSON.stringify(payload, null, 2));
    return { status: 'placeholder', payload };
  }

  const payload = buildPayload(auctionId, instructions);

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (AUTH_TOKEN) headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;

  const resp = await fetch(`${CANTON_URL}/v1/exercise`, {
    method:  'POST',
    headers,
    body:    JSON.stringify(payload),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Canton JSON API ${resp.status}: ${body}`);
  }

  return resp.json();
}

function buildPayload(auctionId: string, instructions: SettlementLeg[]): ExerciseRequest {
  return {
    templateId: TEMPLATE_ID,
    contractId: CONTRACT_ID,
    choice:     CHOICE,
    argument: {
      auctionId,
      settlements: instructions.map(leg => ({
        wallet:     leg.wallet,
        deltaToken: leg.deltaToken.toString(),
        deltaUsdc:  leg.deltaUsdc.toString(),
      })),
    },
  };
}


// ---------------------------------------------------------------------------
// @daml/ledger SDK approach (use this once dpm codegen-js has run)
// ---------------------------------------------------------------------------
//
// 1. Your teammate runs:  dpm codegen-js
//    This generates a package, e.g. @daml.js/auction
//
// 2. Add it: npm install ./path/to/generated/@daml.js/auction
//
// 3. Then replace submitToCantonJsonApi with:
//
// import Ledger from '@daml/ledger';
// import { AuctionSettlement } from '@daml.js/auction';
//
// export async function submitViaLedgerSdk(
//   auctionId:    string,
//   instructions: SettlementLeg[],
// ): Promise<void> {
//   const ledger = new Ledger({
//     token:       AUTH_TOKEN,
//     httpBaseUrl: CANTON_URL,
//   });
//
//   await ledger.exercise(
//     AuctionSettlement.Settle,   // generated choice type — fully type-checked
//     CONTRACT_ID,
//     {
//       auctionId,
//       settlements: instructions.map(leg => ({
//         wallet:     leg.wallet,
//         deltaToken: `${leg.deltaToken}`,
//         deltaUsdc:  `${leg.deltaUsdc}`,
//       })),
//     },
//   );
// }
