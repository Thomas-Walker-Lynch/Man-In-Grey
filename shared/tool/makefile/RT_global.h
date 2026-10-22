#ifndef RT_global_H
#define RT_global_H
  #include <stdint.h>
  #include <stdbool.h>

  typedef unsigned int uint;

  #define Local static
  #define Free(pt) free(pt); (pt) = NULL;

#endif
