// Mesh size
cl__1 = 8e-3;

// Points
Point(6) = {0.0282117401846776, 0.1038364541096209, 0, cl__1};
Point(7) = {0.2051966913511309, 0.4055, 0, cl__1};
Point(8) = {0, 0, 0, cl__1};
Point(13) = {0.0645, 0, 0, cl__1};
Point(14) = {0.0927117401846776, 0.1038364541096209, 0, cl__1};
Point(16) = {0.2696966913511309, 0.4055, 0, cl__1};
Point(21) = {0.0745, 0, 0, cl__1};
Point(22) = {0.1027117401846776, 0.1038364541096209, 0, cl__1};
Point(24) = {0.2796966913511309, 0.4055, 0, cl__1};

// Lines
p1 = newp;
Point(p1 + 1) = {0.2051966913511309, 0, 0};
Circle(1) = {8, p1 + 1, 6};
Line(6) = {6, 7};
p7 = newp;
Point(p7 + 1) = {0.2696966913511309, 0, 0};
Circle(7) = {13, p7 + 1, 14};
Line(8) = {14, 16};
Line(9) = {8, 13};
Line(10) = {7, 16};
p11 = newp;
Point(p11 + 1) = {0.2796966913511309, 0, 0};
Circle(11) = {21, p11 + 1, 22};
Line(12) = {22, 24};
Line(13) = {13, 21};
Line(14) = {16, 24};
Line(18) = {6, 14};   // splits surface 100 at nose/cone junction
Line(19) = {14, 22};  // splits surface 200 at nose/cone junction

// Transfinite settings
Transfinite Line {1, 7, 11} = 21 Using Progression 1;
Transfinite Line {6, 8, 12} = 57 Using Progression 1;
Transfinite Line {9, 18, 10} = 21 Using Progression 1;
Transfinite Line {13, 19, 14} = 4 Using Progression 1;

// Surface 100 TPS split into nose and cone
Line Loop(101) = {1, 18, -7, -9};      // nose cap TPS
Plane Surface(101) = {101};
Line Loop(102) = {6, 10, -8, -18};    // cone TPS
Plane Surface(102) = {102};

// Surface 200 Structure split into nose and cone
Line Loop(201) = {7, 19, -11, -13};    // nose cap structure
Plane Surface(201) = {201};
Line Loop(202) = {8, 14, -12, -19};    // cone structure  
Plane Surface(202) = {202};

// Transfinite properties
Transfinite Surface {101} = {8, 6, 14, 13};
Transfinite Surface {102} = {6, 7, 16, 14};
Transfinite Surface {201} = {13, 14, 22, 21};
Transfinite Surface {202} = {14, 16, 24, 22};
Recombine Surface {101, 102, 201, 202};

// Mesh
Mesh.MshFileVersion = 2.208;
Mesh 2;

// Boundary TPS front
Physical Line("BC 4 400") = {6, 1};
Physical Line("BC 6 600") = {6, 1};
Physical Line("BC 10 1000") = {6, 1};

// Boundary bondline
Physical Line("BC 8 800") = {8, 7}; // Velocity constrain
Physical Line("BC 9 900") = {8, 7}; // Displacement constrain
Physical Line("BC 11 1100") = {8, 7};

// Sides of the TPS and structure, back of the structure
Physical Line("BC 9 901") = {14};
Physical Line("BC 9 902") = {12};
Physical Line("BC 9 903") = {11};
Physical Line("BC 8 801") = {9}; // Velocity constrain
Physical Line("BC 9 904") = {9}; // Displacement constrain
Physical Line("BC 9 905") = {13};

// Assign TPS material 
Physical Surface("MAT PICA") = {101, 102};
Physical Surface("MAT AL6061") = {201, 202};
