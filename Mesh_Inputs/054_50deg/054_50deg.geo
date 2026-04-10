// Mesh size
cl__1 = 1e-2;

// Points
Point(6) = {-0.199669771923225, 0.1675428319780292, 1.860099096729119e-17, cl__1};
Point(7) = {1.085530320146805e-18, 0.4055, 4.50195436485501e-17, cl__1};
Point(8) = {-0.2606503757278911, 4.787964304084237e-17, 1.77194175072624e-33, cl__1};
Point(13) = {-0.1961503757278911, 4.787964304084237e-17, 1.77194175072624e-33, cl__1};
Point(14) = {-0.135169771923225, 0.1675428319780292, 1.860099096729119e-17, cl__1};
Point(15) = {-0.135169771923225, 0.1675428319780292, 1.860099096729119e-17, cl__1};
Point(16) = {0.0645, 0.4055, 4.50195436485501e-17, cl__1};
Point(21) = {-0.1861503757278911, 4.787964304084237e-17, 1.77194175072624e-33, cl__1};
Point(22) = {-0.125169771923225, 0.1675428319780292, 1.860099096729119e-17, cl__1};
Point(23) = {-0.125169771923225, 0.1675428319780292, 1.860099096729119e-17, cl__1};
Point(24) = {0.0745, 0.4055, 4.50195436485501e-17, cl__1};

// Lines
p1 = newp;
Point(p1 + 1) = {0, 0, 0};
Circle(1) = {8, p1 + 1, 6};
Line(6) = {6, 7};
p7 = newp;
Point(p7 + 1) = {0.0645, 0, 0};
Circle(7) = {13, p7 + 1, 14};
Line(8) = {15, 16};
Line(9) = {8, 13};
Line(10) = {7, 16};
p11 = newp;
Point(p11 + 1) = {0.0745, 0, 0};
Circle(11) = {21, p11 + 1, 22};
Line(12) = {23, 24};
Line(13) = {13, 21};
Line(14) = {16, 24};
Line(15) = {14, 16};
Line(16) = {22, 24};
Line(17) = {14, 16};

// Planes
Line Loop(100) = {1, 6, 10, -15, -7, -9};
Plane Surface(100) = {100};
Recombine Surface {100};
Line Loop(200) = {7, 17, 14, -16, -11, -13};
Plane Surface(200) = {200};
Recombine Surface {200};

// Mesh
Mesh 2;

// Boundary TPS front
Physical Line("BC 4 400") = {6, 1};
Physical Line("BC 6 600") = {6, 1};
Physical Line("BC 10 1000") = {6, 1};

// Boundary bondline
Physical Line("BC 9 900") = {8, 7};
Physical Line("BC 11 1100") = {8, 7};

// Sides of the TPS and structure, back of the structure
Physical Line("BC 9 901") = {10};
Physical Line("BC 9 902") = {14};
Physical Line("BC 9 903") = {12};
Physical Line("BC 9 904") = {11};
Physical Line("BC 9 905") = {9};
Physical Line("BC 9 906") = {13};

// Assign TPS material 
Physical Surface("MAT PICA") = {100};
Physical Surface("MAT AL6061") = {200};
