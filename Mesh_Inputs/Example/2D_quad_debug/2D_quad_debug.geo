//dimensions in meters
el = 0.0002;
TPS_thickness=0.0127;
plies=2;
layer1=plies*0.001905;
layer2=TPS_thickness-layer1;
//wide=0.5*TPS_thickness;
wide=0.003;
//Structure=0.0008128;//aerosurface
Structure=0.001016;
Point(1) = {0, 0, 0, el};
Point(2) = {TPS_thickness, 0, 0, el};
Point(3) = {0, wide, 0, el};
Point(4) = {TPS_thickness, wide, 0, el};
Point(5) = {TPS_thickness+Structure, 0, 0, el};
Point(6) = {TPS_thickness+Structure, wide, 0, el};
Line(1) = {1, 2};
Line(2) = {2, 4};
Line(3) = {4, 3};
Line(4) = {3, 1};
Line Loop(6) = {3, 4, 1, 2};
Plane Surface(6) = {6};
Line(5) = {2, 5};
Line(6) = {5, 6};
Line(7) = {6, 4};
Line Loop(7) = {7, -2, 5, 6};
Plane Surface(7) = {7};
Transfinite Surface {6,7};
Recombine Surface {6,7};
//Physical Line("BC 2 200") = {4};//simple heat flux BC
Physical Line("BC 4 400") = {4};//enthalpy based heat flux
Physical Line("BC 6 600") = {4};//surface radiation
Physical Line("BC 8 800") = {2};
Physical Line("BC 8 801") = {1,3};
Physical Line("BC 10 1000") = {4};
Physical Line("BC 11 1100") = {2};
Physical Line("BC 11 1101") = {1,3};
Physical Line("BC 9 900") = {6};
Physical Surface("MAT FM5504mc") = {6};
//Physical Surface("MAT P50_Cork") = {6};
Physical Surface("MAT AL6061") = {7};

Mesh 2;

