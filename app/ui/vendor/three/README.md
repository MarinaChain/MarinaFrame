three.js r170 (npm `three@0.170.0`), MIT licence (see `LICENSE`).

- `three.module.min.js` is `build/three.module.min.js`, unchanged.
- `OrbitControls.js` and `STLLoader.js` are from `examples/jsm/`. One change only: the bare
  `'three'` import is replaced by `'./three.module.min.js'`, so the app needs no import map.
