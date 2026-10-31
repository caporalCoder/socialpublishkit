//! Run only via tests/check_sdk_clients.py against its fake publishing service.
use socialpublishkit::{Platform, PublicationState, PublishRequest, PublishStatus, SocialClient};
use socialpublishkit::{YouTubeOptions, YouTubePrivacy};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = SocialClient::new(
        &std::env::var("SOCIALPUBLISHKIT_TEST_GATEWAY")?,
        "test-gateway-token-".repeat(2),
    )?;
    assert_eq!(client.accounts().await?[0].platform, Platform::Tiktok);
    let mut request = PublishRequest {
        publication_id: "rust-smoke".into(),
        account: "tiktok".into(),
        video: std::env::var("SOCIALPUBLISHKIT_TEST_VIDEO")?.into(),
        caption: "SDK fixture".into(),
        ..Default::default()
    };
    client.publish(&request).await?;
    let mut job = client.publication(&request.publication_id).await?;
    for _ in 0..100 {
        if job.state != PublicationState::Processing {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
        job = client.publication(&request.publication_id).await?;
    }
    assert_eq!(job.state, PublicationState::Completed);
    assert_eq!(job.result.unwrap().status, PublishStatus::DraftDelivered);
    assert_eq!(
        client.publish(&request).await?.result.unwrap().post_id,
        "fake-draft"
    );
    request.caption = "different".into();
    assert!(matches!(
        client.publish(&request).await,
        Err(socialpublishkit::Error::Gateway(Some(409)))
    ));
    request.publication_id = "rust-youtube".into();
    request.account = "youtube".into();
    request.title = "Example".into();
    request.youtube = Some(YouTubeOptions {
        privacy: YouTubePrivacy::Unlisted,
        made_for_kids: true,
        ..Default::default()
    });
    client.publish(&request).await?;
    let mut job = client.publication(&request.publication_id).await?;
    for _ in 0..100 {
        if job.state != PublicationState::Processing {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
        job = client.publication(&request.publication_id).await?;
    }
    assert_eq!(job.state, PublicationState::Completed);
    assert_eq!(job.result.unwrap().status, PublishStatus::Uploaded);
    assert_eq!(
        client.publish(&request).await?.result.unwrap().post_id,
        "fake-youtube"
    );
    println!("Rust gateway contract passed");
    Ok(())
}
