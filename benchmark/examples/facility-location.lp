\ small facility location: 4 depots, 6 customers, fixed cost + assignment
Minimize
 obj: 3 y1 + 5 y2 + 4 y3 + 6 y4 + 2 x11 + 3 x12 + 4 x13 + 2 x14 + 3 x15 + 1 x16 + 4 x21 + 2 x22 + 1 x23 + 3 x24 + 2 x25 + 2 x26 + 3 x31 + 4 x32 + 2 x33 + 1 x34 + 4 x35 + 3 x36 + 2 x41 + 1 x42 + 3 x43 + 4 x44 + 2 x45 + 5 x46
Subject To
 dem1: x11 + x21 + x31 + x41 >= 1
 dem2: x12 + x22 + x32 + x42 >= 1
 dem3: x13 + x23 + x33 + x43 >= 1
 dem4: x14 + x24 + x34 + x44 >= 1
 dem5: x15 + x25 + x35 + x45 >= 1
 dem6: x16 + x26 + x36 + x46 >= 1
 cap1: x11 + x12 + x13 + x14 + x15 + x16 - 3 y1 <= 0
 cap2: x21 + x22 + x23 + x24 + x25 + x26 - 3 y2 <= 0
 cap3: x31 + x32 + x33 + x34 + x35 + x36 - 3 y3 <= 0
 cap4: x41 + x42 + x43 + x44 + x45 + x46 - 3 y4 <= 0
Binary
 y1 y2 y3 y4 x11 x12 x13 x14 x15 x16 x21 x22 x23 x24 x25 x26 x31 x32 x33 x34 x35 x36 x41 x42 x43 x44 x45 x46
End