// Capture of the 3D view as a picture for the PDF report: a fixed size, a white background and no
// controls or labels (they are page elements, not part of the scene). The drawing itself is in
// model3d.js; the numbers and the framing rule are here, so a test can check them.

/** Size of the report picture (px). 16:10 fills the hero slot on page 1 of the report. */
export const CAPTURE_SIZE = { width: 1600, height: 1000 };

/** The first bytes of every PNG file, as base64 text ("\x89PNG\r\n\x1a\n"). */
export const PNG_BASE64_PREFIX = 'iVBORw0KGgo';

/**
 * How much wider the view must be drawn so the picture shows what the pane shows. The camera keeps
 * its vertical field; a picture that is narrower than the pane would cut the sides, so the field
 * grows by the ratio of the two shapes. A picture that is wider than the pane shows more at the
 * sides and needs no change.
 */
export function captureFraming(paneAspect, captureAspect) {
  if (!(paneAspect > 0) || !(captureAspect > 0)) return 1;
  return Math.max(1, paneAspect / captureAspect);
}

/** The base64 text of a PNG data URL ("data:image/png;base64,..."), or null for anything else. */
export function pngBase64(dataUrl) {
  const prefix = 'data:image/png;base64,';
  if (typeof dataUrl !== 'string' || !dataUrl.startsWith(prefix)) return null;
  const text = dataUrl.slice(prefix.length);
  return text.startsWith(PNG_BASE64_PREFIX) ? text : null;
}
