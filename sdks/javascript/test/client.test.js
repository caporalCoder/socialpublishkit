import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SocialClient, GatewayError } from '../index.js';

test('rejects nonlocal HTTP, URL credentials, and unsafe request IDs', async () => {
  assert.throws(() => new SocialClient({ token: 'secret', baseUrl: 'http://example.com' }));
  assert.throws(() => new SocialClient({ token: 'secret', baseUrl: 'https://user:pass@example.com' }));
  const client = new SocialClient({ token: 'secret' });
  await assert.rejects(client.publication('../../secret'));
  assert.equal(JSON.stringify(client), '{}');
});

test('sends video bytes once, preserves request ID, and never infers an AI label', async () => {
  const calls = [];
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const part of req) chunks.push(part);
    calls.push({ path: req.url, headers: req.headers, body: Buffer.concat(chunks).toString() });
    res.writeHead(202, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ id: 'video-job-001', state: 'processing', result: null, error: null, account: 'tiktok' }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const folder = await mkdtemp(join(tmpdir(), 'socialpublishkit-js-'));
  try {
    const video = join(folder, 'video.mp4');
    await writeFile(video, 'fake-video');
    const client = new SocialClient({ token: 'gateway-secret', baseUrl: `http://127.0.0.1:${server.address().port}` });
    const job = await client.publish({ publicationId: 'video-job-001', account: 'tiktok', video, caption: 'Bonjour #CodeExample' });
    assert.equal(job.id, 'video-job-001');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].headers['idempotency-key'], 'video-job-001');
    assert.equal(calls[0].headers.authorization, 'Bearer gateway-secret');
    const body = JSON.parse(calls[0].body);
    assert.equal(Buffer.from(body.video_base64, 'base64').toString(), 'fake-video');
    assert.equal(body.tiktok, undefined);
    assert.equal(body.video, undefined);
  } finally {
    await rm(folder, { recursive: true });
    await new Promise(resolve => server.close(resolve));
  }
});

test('does not leak provider errors or retry failures', async () => {
  let calls = 0;
  const server = http.createServer((req, res) => {
    calls++;
    res.writeHead(503);
    res.end('secret provider token');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const client = new SocialClient({ token: 'secret', baseUrl: `http://127.0.0.1:${server.address().port}` });
    await assert.rejects(client.accounts(), error => error instanceof GatewayError && error.status === 503 && !error.message.includes('secret'));
    assert.equal(calls, 1);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

test('refuses redirects instead of forwarding credentials', async () => {
  let calls = 0;
  const server = http.createServer((req, res) => {
    calls++;
    res.writeHead(302, { Location: '/redirected' });
    res.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const client = new SocialClient({ token: 'secret', baseUrl: `http://127.0.0.1:${server.address().port}` });
    await assert.rejects(client.accounts(), GatewayError);
    assert.equal(calls, 1);
  } finally { await new Promise(resolve => server.close(resolve)); }
});
