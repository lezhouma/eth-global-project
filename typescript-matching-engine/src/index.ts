import 'dotenv/config';
import express, { Request, Response } from 'express';
import { startAuction, addOrder, getStatus, getResult, isOpen } from './auction';

const app  = express();
const PORT = process.env.PORT ?? 3000;

app.use(express.json());

// POST /auction/start  { "durationMinutes": 5 }
app.post('/auction/start', (req: Request, res: Response) => {
  const { durationMinutes } = req.body as { durationMinutes?: number };
  if (!durationMinutes || durationMinutes <= 0) {
    res.status(400).json({ error: 'durationMinutes must be a positive number' });
    return;
  }
  try {
    const endTime = startAuction(durationMinutes);
    res.json({ status: 'started', endTime: endTime.toISOString(), durationMinutes });
  } catch (err) {
    res.status(409).json({ error: (err as Error).message });
  }
});

// POST /orders  { "side": "buy"|"sell", "price": 105, "quantity": 20,
//                 "userId": "ben", "walletAddress": "0x..." }
app.post('/orders', (req: Request, res: Response) => {
  const { side, price, quantity, userId = 'anonymous', walletAddress } =
    req.body as {
      side?:          string;
      price?:         number;
      quantity?:      number;
      userId?:        string;
      walletAddress?: string;
    };

  if (side !== 'buy' && side !== 'sell') {
    res.status(400).json({ error: "side must be 'buy' or 'sell'" });
    return;
  }
  if (price == null || quantity == null) {
    res.status(400).json({ error: 'price and quantity are required' });
    return;
  }
  if (price <= 0 || quantity <= 0) {
    res.status(400).json({ error: 'price and quantity must be positive' });
    return;
  }
  if (!walletAddress) {
    res.status(400).json({ error: 'walletAddress is required' });
    return;
  }

  try {
    const orderId = addOrder(side, price, quantity, userId, walletAddress);
    res.status(201).json({ orderId, status: 'accepted' });
  } catch (err) {
    res.status(409).json({ error: (err as Error).message });
  }
});

// GET /auction/status
app.get('/auction/status', (_req: Request, res: Response) => {
  res.json(getStatus());
});

// GET /auction/result
app.get('/auction/result', (_req: Request, res: Response) => {
  if (isOpen()) {
    res.status(425).json({ error: 'Auction still open — check back after close' });
    return;
  }
  const result = getResult();
  if (!result) {
    res.status(404).json({ error: 'No auction result available yet' });
    return;
  }
  res.json(result);
});

app.listen(PORT, () => {
  console.log(`\nCall Auction Engine — http://localhost:${PORT}`);
  console.log('  POST /auction/start   { durationMinutes }');
  console.log('  POST /orders          { side, price, quantity, userId, walletAddress }');
  console.log('  GET  /auction/status');
  console.log('  GET  /auction/result\n');
});
