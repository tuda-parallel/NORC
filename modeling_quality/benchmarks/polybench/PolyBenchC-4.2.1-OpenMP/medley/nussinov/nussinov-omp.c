/**
 * This version is stamped on May 10, 2016
 *
 * Contact:
 *   Louis-Noel Pouchet <pouchet.ohio-state.edu>
 *   Tomofumi Yuki <tomofumi.yuki.fr>
 *
 * Web address: http://polybench.sourceforge.net
 */
/* nussinov.c: this file is part of PolyBench/C */

#include <stdio.h>
#include <unistd.h>
#include <string.h>
#include <math.h>

/* Include polybench common header. */
#include <polybench.h>

/* Include benchmark-specific header. */
#include "nussinov.h"

/* RNA bases represented as chars, range is [0,3] */
typedef char base;

/* #define match(b1, b2) (((b1)+(b2)) == 3 ? 1 : 0) */
/* #define max_score(s1, s2) ((s1 >= s2) ? s1 : s2) */

/* Array initialization. */
static
void init_array (int n,
                 base POLYBENCH_1D(seq,N,n),
		 DATA_TYPE POLYBENCH_2D(table,N,N,n,n))
{
  int i, j;

  //base is AGCT/0..3
  for (i=0; i <n; i++) {
     seq[i] = (base)((i+1)%4);
  }

  for (i=0; i <n; i++)
     for (j=0; j <n; j++)
       table[i][j] = 0;
}


/* DCE code. Must scan the entire live-out data.
   Can be used also to check the correctness of the output. */
static
void print_array(int n,
		 DATA_TYPE POLYBENCH_2D(table,N,N,n,n))

{
  int i, j;
  int t = 0;

  POLYBENCH_DUMP_START;
  POLYBENCH_DUMP_BEGIN("table");
  for (i = 0; i < n; i++) {
    for (j = i; j < n; j++) {
      if (t % 20 == 0) fprintf (POLYBENCH_DUMP_TARGET, "\n");
      fprintf (POLYBENCH_DUMP_TARGET, DATA_PRINTF_MODIFIER, table[i][j]);
      t++;
    }
  }
  POLYBENCH_DUMP_END("table");
  POLYBENCH_DUMP_FINISH;
}


/* Main computational kernel. The whole function will be timed,
   including the call and return. */
/*
  Original version by Dave Wonnacott at Haverford College <davew@cs.haverford.edu>,
  with help from Allison Lake, Ting Zhou, and Tian Jin,
  based on algorithm by Nussinov, described in Allison Lake's senior thesis.
*/
static
void kernel_nussinov(int n, base POLYBENCH_1D(seq,N,n),
			   DATA_TYPE POLYBENCH_2D(table,N,N,n,n))
{
  int i, j, k, d;

#pragma scop
  /* Wavefront parallelism: iterate by anti-diagonal distance d = j - i.
     All elements with the same d are independent since their dependencies
     (table[i][j-1], table[i+1][j], table[i+1][j-1], table[i][k], table[k+1][j])
     all lie on smaller diagonals (already computed). */
  for (d = 1; d < _PB_N; d++) {
    #pragma omp parallel for private(j, k)
    for (i = _PB_N - 1 - d; i >= 0; i--) {
      j = i + d;

      if (j-1>=0)
        if (table[i][j-1] > table[i][j])
          table[i][j] = table[i][j-1];
      if (i+1<_PB_N)
        if (table[i+1][j] > table[i][j])
          table[i][j] = table[i+1][j];

      if (j-1>=0 && i+1<_PB_N) {
        /* don't allow adjacent elements to bond */
        if (i<j-1) {
          int m_val;
          if (((seq[i])+(seq[j])) == 3)
            m_val = 1;
          else
            m_val = 0;
          if (table[i+1][j-1] + m_val > table[i][j])
            table[i][j] = table[i+1][j-1] + m_val;
        } else {
          if (table[i+1][j-1] > table[i][j])
            table[i][j] = table[i+1][j-1];
        }
      }

      for (k=i+1; k<j; k++) {
        if (table[i][k] + table[k+1][j] > table[i][j])
          table[i][j] = table[i][k] + table[k+1][j];
      }
    }
  }
#pragma endscop

}


int main(int argc, char** argv)
{
  /* Retrieve problem size. */
  int n = N;

  /* Variable declaration/allocation. */
  POLYBENCH_1D_ARRAY_DECL(seq, base, N, n);
  POLYBENCH_2D_ARRAY_DECL(table, DATA_TYPE, N, N, n, n);

  /* Initialize array(s). */
  init_array (n, POLYBENCH_ARRAY(seq), POLYBENCH_ARRAY(table));

  /* Start timer. */
  polybench_start_instruments;

  /* Run kernel. */
  kernel_nussinov (n, POLYBENCH_ARRAY(seq), POLYBENCH_ARRAY(table));

  /* Stop and print timer. */
  polybench_stop_instruments;
  polybench_print_instruments;

  /* Prevent dead-code elimination. All live-out data must be printed
     by the function call in argument. */
  polybench_prevent_dce(print_array(n, POLYBENCH_ARRAY(table)));

  /* Be clean. */
  POLYBENCH_FREE_ARRAY(seq);
  POLYBENCH_FREE_ARRAY(table);

  return 0;
}
