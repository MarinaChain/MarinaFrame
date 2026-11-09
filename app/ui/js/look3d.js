// Look of the 3D view: image-based light from a neutral studio room, a key and a fill light,
// a soft shadow on a ground plane, and physically based materials (hull paint by height,
// steel, tanks by content). The renderer uses the sRGB output and neutral tone mapping, which
// keeps the capacity-plan colours close to their design tokens.
//
// Shadows are drawn once per scene change, not once per frame: the light is fixed to the world,
// so turning the camera does not move a shadow.

import * as THREE from '../vendor/three/three.module.min.js';
import { RoomEnvironment } from '../vendor/three/RoomEnvironment.js';

/** Blur of the studio room for the image-based light (0 sharp, 1 fully blurred). */
const ENVIRONMENT_BLUR = 0.04;
/** Strength of the image-based light; the direct lights add shape on top of it. */
const ENVIRONMENT_INTENSITY = 0.75;
/** Key light from forward, starboard and above (the home view direction), and a weak fill. */
const KEY_DIRECTION = new THREE.Vector3(0.6, -1.0, 1.6).normalize();
const KEY_INTENSITY = 1.5;
const FILL_DIRECTION = new THREE.Vector3(-1.2, 1.0, 0.5).normalize();
const FILL_INTENSITY = 0.35;
/** Shadow map size (texels); PCF soft filtering blurs its edges. */
const SHADOW_MAP_SIZE = 2048;
/** Shadow darkness on the ground plane, light and dark theme. */
const GROUND_SHADOW_OPACITY = { light: 0.2, dark: 0.45 };
/** Ground plane size as a multiple of the model's largest extent. */
const GROUND_SCALE = 4;
/** Lift of an edge line's face behind it, so the line is not hidden by its own face. */
const FACE_OFFSET = { polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 };

/** Material settings by kind. Roughness and metalness are paint and plate values, not measured. */
export const SURFACES = {
  // Hull paint: a satin coating (antifouling, boot top, topside).
  paint: { roughness: 0.55, metalness: 0.0 },
  // Structure steel: primed plate, slightly metallic so the members read as steel.
  steel: { roughness: 0.48, metalness: 0.35 },
  // Tank solids: matte, so the capacity-plan colour stays readable from every angle.
  tank: { roughness: 0.62, metalness: 0.0 },
};

/** Set up colour management, tone mapping and soft shadows on a renderer. */
export function setUpRenderer(renderer) {
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  // The scene renders on demand; shadows update only when the scene changes (markShadows).
  renderer.shadowMap.autoUpdate = false;
}

/**
 * Lights, environment and the ground shadow plane of a scene. `fit(box)` places the shadow
 * camera and the ground under a model box (THREE.Box3); `markShadows()` redraws the shadow map
 * on the next frame; `setTheme(dark)` sets the shadow strength for the theme.
 */
export function createLighting({ renderer, scene }) {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  scene.environment = pmrem.fromScene(room, ENVIRONMENT_BLUR).texture;
  scene.environmentIntensity = ENVIRONMENT_INTENSITY;
  room.dispose?.();
  pmrem.dispose();

  const key = new THREE.DirectionalLight(0xffffff, KEY_INTENSITY);
  key.castShadow = true;
  key.shadow.mapSize.set(SHADOW_MAP_SIZE, SHADOW_MAP_SIZE);
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  const fill = new THREE.DirectionalLight(0xffffff, FILL_INTENSITY);
  scene.add(key, key.target, fill, fill.target);

  const groundMaterial = new THREE.ShadowMaterial({ opacity: GROUND_SHADOW_OPACITY.light, depthWrite: false });
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), groundMaterial);
  ground.receiveShadow = true;
  ground.renderOrder = -1;
  ground.visible = false;
  scene.add(ground);

  function markShadows() {
    renderer.shadowMap.needsUpdate = true;
  }

  return {
    ground,
    /** Place the lights, the shadow camera and the ground under a model box. */
    fit(box) {
      if (!box || box.isEmpty()) {
        ground.visible = false;
        return;
      }
      const centre = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const radius = size.length() / 2;
      for (const [light, direction] of [[key, KEY_DIRECTION], [fill, FILL_DIRECTION]]) {
        light.position.copy(centre).addScaledVector(direction, radius * 3);
        light.target.position.copy(centre);
        light.target.updateMatrixWorld();
      }
      const camera = key.shadow.camera;
      camera.left = -radius * 1.2;
      camera.right = radius * 1.2;
      camera.top = radius * 1.2;
      camera.bottom = -radius * 1.2;
      camera.near = radius * 0.5;
      camera.far = radius * 6;
      camera.updateProjectionMatrix();
      const extent = Math.max(size.x, size.y) * GROUND_SCALE;
      ground.scale.set(extent, extent, 1);
      ground.position.set(centre.x, centre.y, box.min.z - 0.002);
      ground.visible = true;
      markShadows();
    },
    markShadows,
    setTheme(dark) {
      groundMaterial.opacity = dark ? GROUND_SHADOW_OPACITY.dark : GROUND_SHADOW_OPACITY.light;
    },
  };
}

/**
 * Hull paint: antifouling below the boot top, the boot top band around the design waterline,
 * topside above. The zone follows the world height of each pixel, so every part that crosses the
 * waterline (hull, skegs, thrusters) is painted the same way. `paint.uniforms` holds the band
 * and the colours; `paint.setBand([low, high])` and `paint.setColours({...})` change them.
 */
export function createPaintMaterial(options = {}) {
  const uniforms = {
    paintBand: { value: new THREE.Vector2(-1e6, -1e6) },
    paintAntifouling: { value: new THREE.Color(0x8e3b2e) },
    paintBootTop: { value: new THREE.Color(0x2a2d33) },
  };
  const material = new THREE.MeshStandardMaterial({ ...SURFACES.paint, side: THREE.DoubleSide, ...FACE_OFFSET, ...options });
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying float vPaintZ;')
      .replace('#include <project_vertex>', '#include <project_vertex>\nvPaintZ = ( modelMatrix * vec4( transformed, 1.0 ) ).z;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', [
        '#include <common>',
        'varying float vPaintZ;',
        'uniform vec2 paintBand;',
        'uniform vec3 paintAntifouling;',
        'uniform vec3 paintBootTop;',
      ].join('\n'))
      .replace('vec4 diffuseColor = vec4( diffuse, opacity );', [
        // Smooth the zone edges over one pixel, so the waterline is a crisp, unstepped line.
        'float paintEdge = max( fwidth( vPaintZ ), 1e-5 );',
        'float aboveLow = smoothstep( paintBand.x - paintEdge, paintBand.x + paintEdge, vPaintZ );',
        'float aboveHigh = smoothstep( paintBand.y - paintEdge, paintBand.y + paintEdge, vPaintZ );',
        'vec3 paint = mix( paintAntifouling, paintBootTop, aboveLow );',
        'paint = mix( paint, diffuse, aboveHigh );',
        'vec4 diffuseColor = vec4( paint, opacity );',
      ].join('\n'));
  };
  material.customProgramCacheKey = () => 'marinaframe-hull-paint';
  material.userData.paint = uniforms;
  return material;
}

/** Set the paint band and colours of a paint material (topside is the material colour). */
export function stylePaint(material, { band, antifouling, bootTop, topside }) {
  const paint = material.userData.paint;
  if (!paint) return;
  if (band) paint.paintBand.value.set(band[0], band[1]);
  if (antifouling) paint.paintAntifouling.value.copy(antifouling);
  if (bootTop) paint.paintBootTop.value.copy(bootTop);
  if (topside) material.color.copy(topside);
}

/** A steel material for structure members. */
export function createSteelMaterial() {
  return new THREE.MeshStandardMaterial({ ...SURFACES.steel, side: THREE.DoubleSide, ...FACE_OFFSET });
}

/** A tank material; the colour is the tank's capacity-plan token. */
export function createTankMaterial() {
  return new THREE.MeshStandardMaterial({ ...SURFACES.tank, side: THREE.DoubleSide, ...FACE_OFFSET });
}
