three.js r170 (npm `three@0.170.0`), MIT licence (see `LICENSE`).

- `three.module.min.js` is `build/three.module.min.js`, unchanged.
- `OrbitControls.js` and `STLLoader.js` are from `examples/jsm/`. One change only: the bare
  `'three'` import is replaced by `'./three.module.min.js'`, so the app needs no import map.
- `GLTFLoader.js` (`examples/jsm/loaders/`) and `BufferGeometryUtils.js` (`examples/jsm/utils/`),
  added 2026-11-09 for the whole-vessel GLB. Changes only: the bare `'three'` import as above, and
  GLTFLoader imports `'./BufferGeometryUtils.js'` instead of `'../utils/BufferGeometryUtils.js'`.
- `RoomEnvironment.js` (`examples/jsm/environments/`), added 2026-11-09 for the image-based light of
  the 3D view (js/look3d.js). Change only: the bare `'three'` import as above. Copied from a local
  `three@0.170.0` package whose `build/three.module.min.js` is byte-identical to the one here.
