#include "mf_kernels.h"
#include <math.h>

int mf_box_volume(double length, double breadth, double depth, double *volume) {
    if (!volume || !isfinite(length) || !isfinite(breadth) || !isfinite(depth)
        || length < 0.0 || breadth < 0.0 || depth < 0.0) {
        return 1;
    }
    /* Handle zero first to avoid overflow in a mathematically zero product. */
    double result = 0.0;
    if (length != 0.0 && breadth != 0.0 && depth != 0.0) {
        result = length * breadth * depth;
    }
    if (!isfinite(result)) {
        return 1;
    }
    *volume = result;
    return 0;
}
