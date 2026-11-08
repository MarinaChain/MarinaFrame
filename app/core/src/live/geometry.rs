//! Sheet and hull geometry for live steps.
//!
//! - View frames turn the model's view pixels into source-page (sheet) pixels.
//! - Section geometry (panel box and calibration) places a section on the sheet.
//! - Candidate polylines come from the worker catalog (`domain/state.json`).
//! - Section curves come from a build record (`result.json`), resampled for 3D.
use super::SectionCurve;
use crate::artifact::guard_inside_task;
use crate::view;
use marinaframe_control::util;
use serde_json::Value;
use std::path::Path;

/// Points per section curve sent to the UI. One count for all curves lets the
/// 3D view morph a section between builds point by point.
pub(super) const CURVE_POINTS: usize = 64;
/// Most points per sheet polyline (strokes, candidate lines).
const POLYLINE_POINTS: usize = 64;
/// Largest build record read (`result.json` of a build is 0.4 to 1.2 MB).
const MAX_BUILD_RECORD_BYTES: usize = 8 * 1024 * 1024;

pub(super) type Point = [f64; 2];
pub(super) type BoxPx = [f64; 4];

/// Where a model view sits on the sheet: its crop box in sheet pixels and its
/// zoom (view pixels per sheet pixel, per axis).
#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) struct ViewFrame {
    crop: BoxPx,
    scale: Point,
}

impl ViewFrame {
    /// Read a view record: `{view_id, crop_box_px, view_px_per_source_px}` or,
    /// for an artifact, `{view_id, crop_box_px, pixel_size}`.
    pub(super) fn from_value(view: &Value) -> Option<(String, ViewFrame)> {
        let id = view["view_id"].as_str()?.to_string();
        let crop = box_px(&view["crop_box_px"])?;
        let scale = point(&view["view_px_per_source_px"]).or_else(|| {
            let size = point(&view["pixel_size"])?;
            Some([size[0] / (crop[2] - crop[0]), size[1] / (crop[3] - crop[1])])
        })?;
        let usable = scale.iter().all(|s| s.is_finite() && *s > 0.0);
        usable.then_some((id, ViewFrame { crop, scale }))
    }

    pub(super) fn to_sheet(self, view_px: Point) -> Point {
        [
            self.crop[0] + view_px[0] / self.scale[0],
            self.crop[1] + view_px[1] / self.scale[1],
        ]
    }

    /// A length in view pixels as sheet pixels (mean of both axes).
    pub(super) fn length_to_sheet(self, view_px: f64) -> f64 {
        view_px * 2.0 / (self.scale[0] + self.scale[1])
    }
}

/// Body-plan calibration of one section panel.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) struct Calibration {
    centre_px: f64,
    baseline_px: f64,
    pixels_per_metre: f64,
}

impl Calibration {
    pub(super) fn from_value(value: &Value) -> Option<Self> {
        let calibration = Calibration {
            centre_px: value["centerline_px"].as_f64()?,
            baseline_px: value["baseline_px"].as_f64()?,
            pixels_per_metre: value["pixels_per_metre"].as_f64()?,
        };
        (calibration.pixels_per_metre > 0.0).then_some(calibration)
    }

    /// Half-breadth `y` and height `z` in metres as a sheet point. The worker draws
    /// half-breadths to the right of the centreline and heights up from the baseline.
    pub(super) fn to_sheet(self, yz_m: Point) -> Point {
        [
            self.centre_px + yz_m[0] * self.pixels_per_metre,
            self.baseline_px - yz_m[1] * self.pixels_per_metre,
        ]
    }
}

/// What the live view knows about one section on the sheet.
#[derive(Clone, Debug, Default)]
pub(super) struct SectionGeometry {
    pub roi: Option<BoxPx>,
    pub calibration: Option<Calibration>,
}

pub(super) fn point(value: &Value) -> Option<Point> {
    Some([value.get(0)?.as_f64()?, value.get(1)?.as_f64()?])
}

pub(super) fn box_px(value: &Value) -> Option<BoxPx> {
    let get = |i: usize| value.get(i).and_then(Value::as_f64);
    let found = [get(0)?, get(1)?, get(2)?, get(3)?];
    (found[2] > found[0] && found[3] > found[1]).then_some(found)
}

pub(super) fn points(value: &Value) -> Vec<Point> {
    value
        .as_array()
        .map(|list| list.iter().filter_map(point).collect())
        .unwrap_or_default()
}

/// Smallest box around all boxes.
pub(super) fn union(boxes: impl IntoIterator<Item = BoxPx>) -> Option<BoxPx> {
    boxes.into_iter().reduce(|a, b| {
        [
            a[0].min(b[0]),
            a[1].min(b[1]),
            a[2].max(b[2]),
            a[3].max(b[3]),
        ]
    })
}

/// Box around the points, grown by `pad` on each side.
pub(super) fn bounds(points: &[Point], pad: f64) -> Option<BoxPx> {
    let boxes = points.iter().map(|p| [p[0], p[1], p[0], p[1]]);
    union(boxes).map(|b| [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad])
}

pub(super) fn round_to(value: f64, decimals: i32) -> f64 {
    let factor = 10f64.powi(decimals);
    (value * factor).round() / factor
}

/// Sheet pixels to one decimal: enough for drawing, and a smaller payload.
pub(super) fn round_points(points: &[Point]) -> Vec<Point> {
    points
        .iter()
        .map(|p| [round_to(p[0], 1), round_to(p[1], 1)])
        .collect()
}

/// `count` points at equal arc length along the polyline. A polyline with fewer
/// than two points, or no length, is returned as it is.
pub(super) fn resample(points: &[Point], count: usize) -> Vec<Point> {
    let lengths: Vec<f64> = points
        .windows(2)
        .map(|w| (w[1][0] - w[0][0]).hypot(w[1][1] - w[0][1]))
        .collect();
    let total: f64 = lengths.iter().sum();
    if points.len() < 2 || count < 2 || total <= 0.0 || !total.is_finite() {
        return points.to_vec();
    }
    let mut result = Vec::with_capacity(count);
    let mut segment = 0;
    let mut start_of_segment = 0.0;
    for i in 0..count {
        let target = total * i as f64 / (count - 1) as f64;
        while segment < lengths.len() - 1 && start_of_segment + lengths[segment] < target {
            start_of_segment += lengths[segment];
            segment += 1;
        }
        let along = if lengths[segment] > 0.0 {
            ((target - start_of_segment) / lengths[segment]).clamp(0.0, 1.0)
        } else {
            0.0
        };
        let (a, b) = (points[segment], points[segment + 1]);
        result.push([a[0] + (b[0] - a[0]) * along, a[1] + (b[1] - a[1]) * along]);
    }
    result
}

/// At most `count` points of the polyline, evenly spaced by index, ends kept.
fn thin(points: &[Point], count: usize) -> Vec<Point> {
    if points.len() <= count || count < 2 {
        return points.to_vec();
    }
    let step = (points.len() - 1) as f64 / (count - 1) as f64;
    (0..count)
        .map(|i| points[((i as f64 * step).round() as usize).min(points.len() - 1)])
        .collect()
}

/// Sheet polyline of a candidate line, from the section's evidence file when it is
/// there, else from the two catalog anchors. Searches all sections when
/// `section_id` is None.
pub(super) fn candidate_polyline(
    task: &Path,
    domain: &Value,
    section_id: Option<&str>,
    candidate_id: &str,
) -> Option<Vec<Point>> {
    let catalog = domain["catalog"].as_object()?;
    let owner = match section_id {
        Some(id) => id.to_string(),
        None => catalog
            .iter()
            .find(|(_, section)| {
                section["candidates"]
                    .as_array()
                    .is_some_and(|list| list.iter().any(|c| c["candidate_id"] == candidate_id))
            })?
            .0
            .clone(),
    };
    let candidate = catalog
        .get(&owner)?
        .get("candidates")?
        .as_array()?
        .iter()
        .find(|c| c["candidate_id"] == candidate_id)?;
    let traced = view::section_polylines(task, domain, &owner)
        .get(candidate_id)
        .filter(|line| line.len() >= 2)
        .cloned();
    let line = traced.unwrap_or_else(|| points(&candidate["contour_selection"]["anchors_px"]));
    (line.len() >= 2).then(|| round_points(&thin(&line, POLYLINE_POINTS)))
}

/// Section curves of one build (`<build>/result.json`), each resampled to
/// [`CURVE_POINTS`] points in metres. Empty when the record is missing or unreadable.
pub(super) fn build_sections(task: &Path, build_path: &str) -> Vec<SectionCurve> {
    let Ok(file) = guard_inside_task(task, &format!("{build_path}/result.json")) else {
        return vec![];
    };
    let Some(record) = util::read_bounded(&file, MAX_BUILD_RECORD_BYTES)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
    else {
        return vec![];
    };
    record["sections"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|section| {
            let curve = resample(&points(&section["points_yz_m"]), CURVE_POINTS);
            Some(SectionCurve {
                id: section["id"].as_str()?.to_string(),
                x_m: section["x_m"].as_f64()?,
                points_yz_m: curve
                    .iter()
                    .map(|p| [round_to(p[0], 3), round_to(p[1], 3)])
                    .collect(),
                source_label: section["source_label"].as_str().map(String::from),
                ink_rms_m: None,
            })
        })
        .collect()
}
