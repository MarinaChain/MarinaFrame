#include "mf_kernels.h"
#include <float.h>
#include <math.h>
#include <stdio.h>

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "check failed at line %d\n", __LINE__); return 1; \
} } while (0)

int main(void) {
    double result = 17.0;
    CHECK(mf_box_volume(2.0, 3.0, 4.0, &result) == 0 && result == 24.0);
    CHECK(mf_box_volume(0.0, DBL_MAX, DBL_MAX, &result) == 0 && result == 0.0);
    result = 17.0;
    CHECK(mf_box_volume(-1.0, 3.0, 4.0, &result) == 1 && result == 17.0);
    CHECK(mf_box_volume(NAN, 3.0, 4.0, &result) == 1 && result == 17.0);
    CHECK(mf_box_volume(INFINITY, 3.0, 4.0, &result) == 1 && result == 17.0);
    CHECK(mf_box_volume(DBL_MAX, 3.0, 4.0, &result) == 1 && result == 17.0);
    CHECK(mf_box_volume(2.0, 3.0, 4.0, NULL) == 1);
    return 0;
}
