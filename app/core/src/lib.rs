//! Transport-independent backend of the MarinaFrame desktop app.
//!
//! Start at [`backend::Backend`]. Reads (`view`, `events`, `provider_view`,
//! `artifact`) never take the controller lock; actions (`actions`) call the
//! controller on a background thread. No Tauri or HTTP types appear in this crate.
pub mod actions;
pub mod artifact;
pub mod backend;
pub mod draft_view;
pub mod error;
pub mod events;
pub mod export;
pub mod files;
pub mod intake;
pub mod live;
pub mod model_keys;
pub mod provider_view;
pub mod storage;
pub mod types;
pub mod view;

pub use backend::Backend;
pub use error::{AppError, AppResult};
pub use storage::AppPaths;
