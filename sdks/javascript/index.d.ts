export type Platform = 'facebook_page' | 'instagram' | 'tiktok' | 'youtube';
export interface AccountSummary { id: string; platform: Platform; account_id: string; name: string }
export interface TikTokOptions {
  mode?: 'draft' | 'private' | 'public';
  duration_seconds?: number;
  disable_comment?: boolean;
  disable_duet?: boolean;
  disable_stitch?: boolean;
  paid_partnership?: boolean;
  own_brand?: boolean;
  ai_generated?: boolean | null;
}
export interface PublishResult {
  platform: Platform; status: 'draft_delivered' | 'uploaded' | 'published';
  post_id: string; url: string; note: string;
}
export interface YouTubeOptions {
  privacy?: 'private' | 'unlisted' | 'public';
  made_for_kids?: boolean;
  category_id?: string | null;
  language?: string | null;
}
export interface Publication {
  id: string; account: string; state: 'processing' | 'completed' | 'failed' | 'unknown';
  result: PublishResult | null; error: string | null;
}
export class GatewayError extends Error { status: number | null; constructor(status?: number | null) }
export class SocialClient {
  constructor(options: { token: string; baseUrl?: string });
  accounts(): Promise<AccountSummary[]>;
  publication(publicationId: string): Promise<Publication>;
  publish(options: {
    publicationId: string; account: string; video: string; caption: string;
    title?: string; tags?: string[]; tiktok?: TikTokOptions; youtube?: YouTubeOptions;
  }): Promise<Publication>;
}
