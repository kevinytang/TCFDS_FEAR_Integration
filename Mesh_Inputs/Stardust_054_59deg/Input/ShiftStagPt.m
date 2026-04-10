clc; clear; close all;

% Old coordinates
xcorr = [-0.1769849511664533, 0, -0.2051966913511309, -0.1406966913511309, ...
    -0.1124849511664533, -0.1124849511664533, 0.0645, -0.1306966913511309, ...
    -0.1024849511664533, -0.1024849511664533, 0.0745];

% Shifted coordinates
xcorr_new = xcorr + 0.2051966913511309;

% Display with fixed 16 decimal places
fprintf('xcorr_new = [\n');
for i = 1:length(xcorr_new)
    fprintf('    %.16f', xcorr_new(i));
    if i < length(xcorr_new)
        fprintf(', ...\n');
    end
end
fprintf('\n];\n');