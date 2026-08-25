\ small mixed integer blending (continuous x1,x2, integer x3)
Minimize
 obj: 2 x1 + 3 x2 + 4 x3
Subject To
 need: x1 + x2 >= 5
 cap1: 3 x1 + 2 x2 + 1 x3 <= 20
 cap2: x3 <= 4
Bounds
 0 <= x1 <= 10
 0 <= x2 <= 10
 0 <= x3 <= 4
Integer
 x3
End