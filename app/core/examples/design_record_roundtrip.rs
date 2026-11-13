//! Read a strict v1 record from stdin, validate it, and emit JSON to stdout.
use marinaframe_app_core::design_record::DesignRecord;
use std::io::{self, Read};

fn main() -> Result<(), String> {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .map_err(|e| e.to_string())?;
    println!("{}", DesignRecord::from_json(&input)?.to_json()?);
    Ok(())
}
