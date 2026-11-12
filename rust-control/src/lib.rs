//! Library face of the MarinaFrame control plane. The `marinaframe` binary and the
//! desktop app both call the same controller functions, so every check applies
//! to both.
pub mod controller;
pub mod models;
pub mod provider;
pub mod station_numbers;
pub mod store;
pub mod supervised;
pub mod table_reading;
pub mod types;
pub mod util;
pub mod validation;
pub mod worker;
