//! The model-eligible images that go with a live decision request.
use super::investigation_mode;
use crate::provider::{self, ImageReceipt};
use crate::store::Store;
use crate::util::{self, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::Value;
use std::collections::BTreeMap;

type BoundImage = (u64, Value, Option<String>, Option<String>, Option<String>);
fn visit(
    v: &Value,
    seq: u64,
    g: &Option<String>,
    r: &Option<String>,
    step: &Option<String>,
    out: &mut BTreeMap<String, BoundImage>,
) {
    match v {
        Value::Object(o) => {
            if v["model_eligible"] == true && v["mime_type"] == "image/png" {
                if let Some(id) = v["id"].as_str() {
                    out.insert(
                        id.into(),
                        (
                            seq,
                            v.clone(),
                            v["generation_id"].as_str().map(String::from).or(g.clone()),
                            v["revision_id"].as_str().map(String::from).or(r.clone()),
                            v["step_sha256"].as_str().map(String::from).or(step.clone()),
                        ),
                    );
                }
            }
            for value in o.values() {
                visit(value, seq, g, r, step, out);
            }
        }
        Value::Array(a) => {
            for value in a {
                visit(value, seq, g, r, step, out);
            }
        }
        _ => (),
    }
}

pub(super) fn collect_images(store: &Store) -> Result<Vec<(ImageReceipt, String)>> {
    let mut found = BTreeMap::<String, BoundImage>::new();
    for e in &store.events {
        let o = &e.payload["response"]["result"];
        let g = o["rendered_generation_id"].as_str().map(String::from);
        let r = o["rendered_revision_id"].as_str().map(String::from);
        let step = o["geometry_audit"]["step_sha256"]
            .as_str()
            .map(String::from);
        visit(o, e.sequence, &g, &r, &step, &mut found);
    }
    let mut values = found.into_values().collect::<Vec<_>>();
    values.retain(|(_, a, g, r, _)| {
        a.get("view").is_none()
            || (g == &store.state.generation_id && r == &store.state.revision_id)
    });
    let investigating = investigation_mode(store);
    if investigating {
        // The model asked for these pixels: the newest views come first.
        let recalled = store.state.last_observation["recalled_view_id"].as_str();
        values.sort_by_key(|(seq, artifact, _, _, _)| {
            (
                recalled.is_none_or(|id| artifact["view_id"] != id),
                std::cmp::Reverse(*seq),
            )
        });
    } else {
        values.sort_by_key(|(seq, a, _, _, _)| (!a.get("view").is_some(), std::cmp::Reverse(*seq)));
    }
    // Preserve at least one source observation beside current CAD observations.
    let mut chosen = vec![];
    if investigating {
        chosen.extend(
            values
                .iter()
                .take(store.state.config.limits.max_images_per_request)
                .cloned(),
        );
    } else if let Some(source) = values
        .iter()
        .filter(|(_, a, _, _, _)| a.get("view").is_none())
        .min_by_key(|(seq, a, _, _, _)| {
            (a["evidence_kind"] != "source_page", std::cmp::Reverse(*seq))
        })
    {
        chosen.push(source.clone());
    }
    for v in values {
        if chosen.len() >= store.state.config.limits.max_images_per_request {
            break;
        }
        if !chosen.iter().any(|x| x.1["id"] == v.1["id"]) {
            chosen.push(v);
        }
    }
    let mut images = vec![];
    for (_, a, g, r, step) in chosen {
        let path = a["path"].as_str().ok_or("image_path")?;
        let bytes = util::read_bounded(
            &util::safe_file(&store.path, path)?,
            store.state.config.limits.max_image_bytes,
        )?;
        provider::check_png(&bytes)?;
        let sha = util::hash(&bytes);
        if a["sha256"] != sha {
            return Err("image_hash_changed".into());
        }
        let meta = ImageReceipt {
            artifact_id: a["id"].as_str().ok_or("image_id")?.into(),
            path: path.into(),
            sha256: sha,
            bytes: bytes.len() as u64,
            mime_type: "image/png".into(),
            evidence_kind: if a["view"].is_string() && !a["evidence_kind"].is_string() {
                "step_reimport_render"
            } else {
                a["evidence_kind"]
                    .as_str()
                    .or(a["kind"].as_str())
                    .unwrap_or("unknown")
            }
            .into(),
            view: a["view"].as_str().map(String::from),
            generation_id: g,
            revision_id: r,
            step_sha256: step,
            pixels_attached: true,
            // Investigation receipts record the sheet region and the pixel
            // size of every image sent.
            crop_box_px: if investigating {
                serde_json::from_value(a["crop_box_px"].clone()).ok()
            } else {
                None
            },
            pixel_size: investigating.then(|| provider::png_size(&bytes)),
        };
        images.push((meta, STANDARD.encode(bytes)));
    }
    Ok(images)
}
