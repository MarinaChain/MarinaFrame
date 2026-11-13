#ifndef MF_KERNELS_H
#define MF_KERNELS_H

#if defined(_WIN32) && defined(MF_SHARED)
# ifdef MF_BUILD
#  define MF_API __declspec(dllexport)
# else
#  define MF_API __declspec(dllimport)
# endif
#else
# define MF_API
#endif

#ifdef __cplusplus
extern "C" {
#endif
/* SI inputs in m, output in m3. Returns 0 on success, 1 on invalid input.
 * Output is unchanged on error. This is a sample, not a hull-volume method. */
MF_API int mf_box_volume(double length, double breadth, double depth, double *volume);
#ifdef __cplusplus
}
#endif
#endif
