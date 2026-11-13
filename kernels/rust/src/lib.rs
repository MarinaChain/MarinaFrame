//! Safe caller for the neutral sample C ABI. Units: m in, m3 out.
extern "C" {
    fn mf_box_volume(length: f64, breadth: f64, depth: f64, volume: *mut f64) -> i32;
}

#[derive(Debug, PartialEq)]
pub struct InvalidDimensions;

pub fn box_volume(length_m: f64, breadth_m: f64, depth_m: f64) -> Result<f64, InvalidDimensions> {
    let mut result = 0.0;
    // SAFETY: the ABI takes three values and a valid writable double for this call.
    let status = unsafe { mf_box_volume(length_m, breadth_m, depth_m, &mut result) };
    if status == 0 {
        Ok(result)
    } else {
        Err(InvalidDimensions)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn volume_and_zero() {
        assert_eq!(box_volume(2.0, 3.0, 4.0), Ok(24.0));
        assert_eq!(box_volume(0.0, f64::MAX, f64::MAX), Ok(0.0));
    }

    #[test]
    fn invalid_dimensions() {
        for value in [-1.0, f64::NAN, f64::INFINITY, f64::MAX] {
            assert_eq!(box_volume(value, 3.0, 4.0), Err(InvalidDimensions));
        }
    }
}
