\ small cut-polytope style MIP on a 6-node graph
Maximize
 obj: 4 z12 + 3 z13 + 0 z14 + 2 z15 + 5 z16 + 3 z23 + 4 z24 + 1 z25 + 2 z26 + 2 z34 + 3 z35 + 4 z36 + 1 z45 + 3 z46 + 2 z56
Subject To
 tri123: z12 + z13 - z23 <= 1
 tri345: z34 + z35 - z45 <= 1
 quad1: z12 - z16 + z26 >= -1
 quad2: z12 - z16 + z26 <= 1
Binary
 z12 z13 z14 z15 z16 z23 z24 z25 z26 z34 z35 z36 z45 z46 z56
End