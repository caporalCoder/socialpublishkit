// Run only via tests/check_sdk_clients.py against its fake publishing service.
import assert from 'node:assert/strict';
import { SocialClient } from '../index.js';
const client = new SocialClient({ token: 'test-gateway-token-'.repeat(2), baseUrl: process.env.SOCIALPUBLISHKIT_TEST_GATEWAY });
assert.equal((await client.accounts())[0].platform, 'tiktok');
const request = { publicationId: 'javascript-smoke', account: 'tiktok', video: process.env.SOCIALPUBLISHKIT_TEST_VIDEO, caption: 'SDK fixture' };
await client.publish(request);
let job;
for (let i = 0; i < 100; i++) {
  job = await client.publication(request.publicationId);
  if (job.state !== 'processing') break;
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.equal(job.state, 'completed');
assert.equal(job.result.status, 'draft_delivered');
assert.equal((await client.publish(request)).result.post_id, 'fake-draft');
await assert.rejects(client.publish({ ...request, caption: 'different' }), e => e.status === 409);
const youtube = { ...request, publicationId: 'javascript-youtube', account: 'youtube',
  title: 'Example', youtube: { privacy: 'unlisted', made_for_kids: true } };
await client.publish(youtube);
for (let i = 0; i < 100; i++) {
  job = await client.publication(youtube.publicationId);
  if (job.state !== 'processing') break;
  await new Promise(resolve => setTimeout(resolve, 20));
}
assert.equal(job.state, 'completed');
assert.equal(job.result.status, 'uploaded');
assert.equal((await client.publish(youtube)).result.post_id, 'fake-youtube');
console.log('JavaScript gateway contract passed');
