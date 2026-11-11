use marinaframe_control::provider::vision::{parse_reply, VisionReply};
use marinaframe_control::provider::Purpose;

#[test]
fn localisation_is_typed_and_cannot_approve() {
    let purpose: Purpose = serde_json::from_str("\"localisation\"").unwrap();
    let good =
        r#"{"answers":[{"id":"A","x":123.5,"y":45.0,"value":null,"evidence":"black cross"}]}"#;
    assert!(matches!(
        parse_reply(purpose, good, &[]).unwrap(),
        VisionReply::Localisation(_)
    ));
    assert!(purpose.prompt().contains("JSON"));
    for bad in [
        good.replace("123.5", "1e99"),
        good.replace("black cross", ""),
        good.replace("\"answers\"", "\"approved\""),
    ] {
        assert!(parse_reply(purpose, &bad, &[]).is_err());
    }
}
