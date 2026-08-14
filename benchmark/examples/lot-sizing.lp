\ small production/lot-sizing MIP (4 periods, 2 limits)
Minimize
 obj: 5 p1 + 5 p2 + 5 p3 + 5 p4 + 2 s1 + 2 s2 + 2 s3 + 2 s4 + 50 y1 + 50 y2 + 50 y3 + 50 y4
Subject To
 demand1: p1 + s0 - s1 >= 3
 demand2: p2 + s1 - s2 >= 4
 demand3: p3 + s2 - s3 >= 2
 demand4: p4 + s3 - s4 >= 5
 capacity1: p1 - 6 y1 <= 0
 capacity2: p2 - 6 y2 <= 0
 capacity3: p3 - 6 y3 <= 0
 capacity4: p4 - 6 y4 <= 0
Bounds
 0 <= s0 <= 4
General
 p1 p2 p3 p4 s0 s1 s2 s3 s4 y1 y2 y3 y4
End