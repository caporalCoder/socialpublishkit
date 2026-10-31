//! Official-API video publishing through a local SocialPublishKit gateway.
//! No automatic retries. Reuse the same publication ID for an identical request.

use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::{fmt, path::PathBuf, time::Duration};

#[derive(Debug)]
pub enum Error {
    InvalidInput(&'static str),
    File,
    Gateway(Option<u16>),
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidInput(message) => f.write_str(message),
            Self::File => f.write_str("Cannot read video file"),
            Self::Gateway(status) => write!(f, "Gateway request failed ({status:?}). Query the same publication ID before retrying."),
        }
    }
}
impl std::error::Error for Error {}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    FacebookPage,
    Instagram,
    Tiktok,
    Youtube,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PublishStatus {
    DraftDelivered,
    Uploaded,
    Published,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PublicationState {
    Processing,
    Completed,
    Failed,
    Unknown,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AccountSummary {
    pub id: String,
    pub platform: Platform,
    pub account_id: String,
    pub name: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PublishResult {
    pub platform: Platform,
    pub status: PublishStatus,
    pub post_id: String,
    pub url: String,
    pub note: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Publication {
    pub id: String,
    pub account: String,
    pub state: PublicationState,
    pub result: Option<PublishResult>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum TikTokMode {
    #[default]
    Draft,
    Private,
    Public,
}

#[derive(Debug, Clone, Serialize)]
pub struct TikTokOptions {
    pub mode: TikTokMode,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_seconds: Option<f64>,
    pub disable_comment: bool,
    pub disable_duet: bool,
    pub disable_stitch: bool,
    pub paid_partnership: bool,
    pub own_brand: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ai_generated: Option<bool>,
}
impl Default for TikTokOptions {
    fn default() -> Self {
        Self {
            mode: TikTokMode::Draft,
            duration_seconds: None,
            disable_comment: true,
            disable_duet: true,
            disable_stitch: true,
            paid_partnership: false,
            own_brand: false,
            ai_generated: None,
        }
    }
}

#[derive(Debug, Default)]
pub struct PublishRequest {
    pub publication_id: String,
    pub account: String,
    pub video: PathBuf,
    pub caption: String,
    pub title: String,
    pub tags: Vec<String>,
    pub tiktok: Option<TikTokOptions>,
}

// Deliberately no Debug: never print the bearer token.
#[derive(Clone)]
pub struct SocialClient {
    http: reqwest::Client,
    base_url: String,
    token: String,
}

fn check_key(key: &str) -> Result<(), Error> {
    if !(8..=128).contains(&key.len())
        || !key
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err(Error::InvalidInput(
            "Use a stable 8-128 character publication ID",
        ));
    }
    Ok(())
}

impl SocialClient {
    pub fn new(base_url: &str, token: impl Into<String>) -> Result<Self, Error> {
        let url = reqwest::Url::parse(base_url)
            .map_err(|_| Error::InvalidInput("Invalid gateway URL"))?;
        if !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || url.path() != "/"
            || (url.scheme() == "http"
                && !matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]")))
        {
            return Err(Error::InvalidInput(
                "Use HTTPS or a loopback HTTP gateway URL without credentials/path/query",
            ));
        }
        let token = token.into();
        if token.is_empty() || !token.bytes().all(|c| (33..=126).contains(&c)) {
            return Err(Error::InvalidInput(
                "A nonempty ASCII bearer token without whitespace is required",
            ));
        }
        let http = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .retry(reqwest::retry::never())
            .timeout(Duration::from_secs(120))
            .build()
            .map_err(|_| Error::Gateway(None))?;
        Ok(Self {
            http,
            base_url: base_url.trim_end_matches('/').to_owned(),
            token,
        })
    }

    async fn request<T: DeserializeOwned>(
        &self,
        path: &str,
        body: Option<serde_json::Value>,
        key: Option<&str>,
    ) -> Result<T, Error> {
        let url = format!("{}{path}", self.base_url);
        let mut request = if let Some(body) = body {
            self.http.post(url).json(&body)
        } else {
            self.http.get(url)
        };
        request = request.bearer_auth(&self.token);
        if let Some(key) = key {
            request = request.header("Idempotency-Key", key);
        }
        let response = request.send().await.map_err(|_| Error::Gateway(None))?;
        let status = response.status();
        if !status.is_success() {
            return Err(Error::Gateway(Some(status.as_u16())));
        }
        response
            .json()
            .await
            .map_err(|_| Error::Gateway(Some(status.as_u16())))
    }

    pub async fn accounts(&self) -> Result<Vec<AccountSummary>, Error> {
        #[derive(Deserialize)]
        struct Accounts {
            accounts: Vec<AccountSummary>,
        }
        let response: Accounts = self.request("/v1/accounts", None, None).await?;
        Ok(response.accounts)
    }

    pub async fn publication(&self, publication_id: &str) -> Result<Publication, Error> {
        check_key(publication_id)?;
        self.request(&format!("/v1/publications/{publication_id}"), None, None)
            .await
    }

    pub async fn publish(&self, post: &PublishRequest) -> Result<Publication, Error> {
        check_key(&post.publication_id)?;
        let metadata = tokio::fs::metadata(&post.video)
            .await
            .map_err(|_| Error::File)?;
        let mp4 = post
            .video
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.eq_ignore_ascii_case("mp4"))
            .unwrap_or(false);
        if !mp4 || !metadata.is_file() || metadata.len() == 0 || metadata.len() > 32 * 1024 * 1024 {
            return Err(Error::InvalidInput("Provide a nonempty MP4 up to 32 MiB"));
        }
        let video = tokio::fs::read(&post.video)
            .await
            .map_err(|_| Error::File)?;
        let mut body = serde_json::json!({"account": post.account, "video_base64": STANDARD.encode(video),
            "caption": post.caption, "title": post.title, "tags": post.tags});
        if let Some(options) = &post.tiktok {
            if options
                .duration_seconds
                .is_some_and(|d| !d.is_finite() || d <= 0.0)
            {
                return Err(Error::InvalidInput(
                    "duration_seconds must be finite and positive",
                ));
            }
            body["tiktok"] = serde_json::to_value(options)
                .map_err(|_| Error::InvalidInput("Invalid TikTok options"))?;
        }
        self.request("/v1/publications", Some(body), Some(&post.publication_id))
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unsafe_urls_and_tokens() {
        assert!(SocialClient::new("http://example.com", "secret").is_err());
        assert!(SocialClient::new("https://a.example/?key=secret", "secret").is_err());
        assert!(SocialClient::new("http://127.0.0.1:8787", "x\r\ny").is_err());
        assert!(SocialClient::new("http://127.0.0.1:8787", "secret").is_ok());
        assert!(check_key("../../secrets").is_err());
    }
    #[test]
    fn never_infers_ai_disclosure() {
        let options = serde_json::to_value(TikTokOptions::default()).unwrap();
        assert_eq!(options["mode"], "draft");
        assert!(options.get("ai_generated").is_none());
    }
}
