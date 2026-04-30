import { describe, it, expect } from 'vitest';
import { createQueue } from '../../src/lib/queue.js';

describe('queue', () => {
  it('enqueues and drains FIFO', async () => {
    const q = createQueue('test_q', { maxSize: 10 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 });
    expect(await q.size()).toBe(2);
    expect(await q.peek(2)).toEqual([{ id: 1 }, { id: 2 }]);
    expect(await q.drainHead(1)).toEqual([{ id: 1 }]);
    expect(await q.size()).toBe(1);
  });

  it('drops the oldest when maxSize exceeded', async () => {
    const q = createQueue('test_q', { maxSize: 3 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 });
    await q.enqueue({ id: 3 });
    await q.enqueue({ id: 4 });
    expect(await q.peek(10)).toEqual([{ id: 2 }, { id: 3 }, { id: 4 }]);
    expect(await q.droppedCount()).toBe(1);
  });

  it('persists across new instances (simulates worker resume)', async () => {
    const q1 = createQueue('test_q', { maxSize: 10 });
    await q1.enqueue({ id: 'survive' });
    const q2 = createQueue('test_q', { maxSize: 10 });
    expect(await q2.peek(1)).toEqual([{ id: 'survive' }]);
  });

  it('returnHead puts items back in original order', async () => {
    const q = createQueue('test_q', { maxSize: 10 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 });
    await q.enqueue({ id: 3 });
    const head = await q.drainHead(2);
    await q.returnHead(head);
    expect(await q.peek(3)).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }]);
  });

  it('clear empties the queue but keeps droppedCount', async () => {
    const q = createQueue('test_q', { maxSize: 1 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 }); // drops 1
    await q.clear();
    expect(await q.size()).toBe(0);
    expect(await q.droppedCount()).toBe(1);
  });

  it('enqueues concurrently without losing items', async () => {
    const q = createQueue('q_concurrent', { maxSize: 1000 });
    const N = 100;
    const promises = [];
    for (let i = 0; i < N; i++) promises.push(q.enqueue({ id: i }));
    await Promise.all(promises);
    expect(await q.size()).toBe(N);
  });

  it('drains and returns concurrently without item loss', async () => {
    const q = createQueue('q_drain_concurrent', { maxSize: 1000 });
    for (let i = 0; i < 10; i++) await q.enqueue({ id: i });
    const [a, b] = await Promise.all([q.drainHead(5), q.drainHead(5)]);
    expect(a.length + b.length).toBe(10);
    expect(await q.size()).toBe(0);
  });

  it('drops oldest items when serialized total exceeds maxBytes', async () => {
    const q = createQueue('q_bytes', { maxSize: 1000, maxBytes: 1000 });
    const big = 'x'.repeat(400); // ~430 bytes once serialized
    for (let i = 0; i < 5; i++) await q.enqueue({ id: i, data: big });
    // 5 × ~430 = ~2150 bytes; budget is 1000 bytes
    const remaining = await q.peek(100);
    const totalBytes = JSON.stringify(remaining).length;
    expect(totalBytes).toBeLessThanOrEqual(1000);
    expect(await q.droppedCount()).toBeGreaterThan(0);
    // Most recent item must be retained
    expect(remaining[remaining.length - 1].id).toBe(4);
  });
});
