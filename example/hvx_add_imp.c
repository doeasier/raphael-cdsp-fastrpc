/*============================================================================
 * hvx_add_imp.c - DSP (cDSP / Hexagon 690 V66) side implementation.
 *
 * QAIC generated gen/hvx_add_skel.c calls __QAIC_IMPL(hvx_add_*) which we
 * define here. This file is compiled with hexagon-clang for the DSP.
 *
 * open/close just manage a dummy handle (the real PD/session is set up by
 * the fastrpc framework). addVec does the actual vector add on the DSP.
 * A scalar loop is used for correctness; HVX 1024-bit intrinsics can be
 * added later (the compute runs on Hexagon 690 regardless).
 *============================================================================*/

#include <stdlib.h>
#include "hvx_add.h"

int hvx_add_open(const char* uri, remote_handle64* handle) {
   void* tptr = malloc(1);
   *handle = (remote_handle64)tptr;
   return 0;
}

int hvx_add_close(remote_handle64 handle) {
   if (handle) free((void*)handle);
   return 0;
}

int hvx_add_rpc_init(remote_handle64 h) {
   (void)h;
   /* one-time DSP-side setup hook (e.g. HVX mode check) */
   return 0;
}

int hvx_add_addVec(remote_handle64 _h,
                   const int32* a, int aLen,
                   const int32* b, int bLen,
                   int32* result, int resultLen) {
   int i;
   (void)_h; (void)aLen; (void)bLen;
   for (i = 0; i < resultLen; i++) {
      result[i] = a[i] + b[i];
   }
   return 0;
}
