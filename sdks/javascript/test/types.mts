import { SocialClient, GatewayError, type Publication, type YouTubeOptions } from '../index.js';

const client = new SocialClient({ token: 'test-token' });
const options: YouTubeOptions = { privacy: 'unlisted', made_for_kids: false };
const publication: Promise<Publication> = client.publish({
  publicationId: 'test-publication', account: 'youtube', video: 'example.mp4',
  caption: 'Example', title: 'Example', youtube: options,
});
void publication;
const status: number | null = new GatewayError(401).status;
void status;
// @ts-expect-error Invalid privacy choices must fail type checking.
const invalid: YouTubeOptions = { privacy: 'friends-only' };
void invalid;
