import { readFile, stat } from 'node:fs/promises';
import { extname } from 'node:path';

export class GatewayError extends Error {
  constructor(status = null) {
    super(`Gateway request failed (${status ?? 'connection'}). Query the same publication ID before retrying.`);
    this.name = 'GatewayError';
    this.status = status;
  }
}

function checkKey(key) {
  if (typeof key !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(key)) {
    throw new TypeError('Use a stable 8-128 character publication ID.');
  }
}

export class SocialClient {
  #token;
  #baseUrl;
  constructor({ token, baseUrl = 'http://127.0.0.1:8787' }) {
    const url = new URL(baseUrl);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
        url.search || url.hash || url.pathname !== '/' ||
        (url.protocol === 'http:' && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))) {
      throw new TypeError('Use HTTPS or a loopback HTTP gateway URL without credentials/path/query.');
    }
    if (typeof token !== 'string' || !/^[\x21-\x7e]+$/.test(token)) {
      throw new TypeError('A nonempty ASCII bearer token without whitespace is required.');
    }
    this.#token = token;
    this.#baseUrl = url.origin;
  }

  async #request(path, body, key) {
    let response;
    try {
      response = await fetch(this.#baseUrl + path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${this.#token}`, 'Content-Type': 'application/json',
          ...(key ? { 'Idempotency-Key': key } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
        redirect: 'error', signal: AbortSignal.timeout(120_000),
      });
    } catch {
      throw new GatewayError();
    }
    if (!response.ok) throw new GatewayError(response.status);
    try { return await response.json(); } catch { throw new GatewayError(response.status); }
  }

  async accounts() { return (await this.#request('/v1/accounts')).accounts; }

  async publication(publicationId) {
    checkKey(publicationId);
    return this.#request(`/v1/publications/${publicationId}`);
  }

  async publish({ publicationId, account, video, caption, title = '', tags = [], tiktok, youtube }) {
    checkKey(publicationId);
    const info = await stat(video);
    if (extname(video).toLowerCase() !== '.mp4' || !info.isFile() || info.size <= 0 || info.size > 32 * 1024 * 1024) {
      throw new TypeError('Provide a nonempty MP4 up to 32 MiB.');
    }
    const body = { account, video_base64: (await readFile(video)).toString('base64'), caption, title, tags };
    if (tiktok !== undefined) body.tiktok = tiktok;
    if (youtube !== undefined) body.youtube = youtube;
    return this.#request('/v1/publications', body, publicationId);
  }
}
