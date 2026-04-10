ch iclc; clear; close all;

% Import excel file
filename = "Run20.xlsx";
data = readtable(filename);

% Input nose radius
r_nose = 0.21;

% Ratio of specific heats
gamma = 1.4;

% Calculate the stagnation heat flux using Sutton-Graves
q_stag = 0.000174153 .* sqrt(data.density_kg_m3_ ./ r_nose) .* ...
    data.velocity_m_s_ .^3; % W/m^2

% Recovery enthalpy
Hr = data.velocity_m_s_.^2 ./ 2;

% Coefficient
rho_u_CH0 = q_stag ./ Hr;

% Freestream pressure in Pa
p1_pa = data.pressure_Kpa_ .* 1000;

% Normal shock pressure ratio: p2/p1 = (2*gamma*M^2 - (gamma-1)) / (gamma+1)
M = data.mach;
shock_ratio = (2 .* gamma .* M.^2 - (gamma - 1)) ./ (gamma + 1);
shock_ratio = max(shock_ratio, 1);

% Post-shock pressure
p2_pa  = p1_pa .* shock_ratio;          % Pa
p2_atm = p2_pa .* (1 / 101325);        % atm

% Append computed columns to data table
data.q_stag_W_m2      = q_stag;
data.Hr               = Hr;
data.rho_u_CH0        = rho_u_CH0;
data.p_freestream_atm = p1_pa ./ 101325;
data.shock_ratio      = shock_ratio;
data.p2_atm           = p2_atm;

% Overwrite the original Excel file with updated data
writetable(data, filename);

% -------------------------------------------------------------------------
% Build FEAR input table
% -------------------------------------------------------------------------
n = height(data);
time = data.time_s_;

% Prepend t=0 row using first data point values
time_full  = [0;          time];
Hr_full    = [Hr(1);      Hr];
qrad_full  = zeros(n+1, 1);
rho_full   = [rho_u_CH0(1); rho_u_CH0];
p2atm_full = [p2_atm(1);  p2_atm];      % post-shock pressure in atm
blow_full  = 0.5 * ones(n+1, 1);
temp_full  = [data.temperature_K_(1); data.temperature_K_];

% BC label: first row labeled, rest blank
N = n + 1;
bc4_labels  = [{"BC 4 400"};  repmat({''}, N-1, 1)];
bc6_labels  = [{"BC 6 600"};  repmat({''}, N-1, 1)];
bc10_labels = [{"BC 10 1000"}; repmat({''}, N-1, 1)];

% Separator columns
sep = repmat({''}, N, 1);

% Assemble the FEAR input table
fear_table = table(...
    bc4_labels,   time_full, Hr_full,   qrad_full, rho_full,  p2atm_full, blow_full, sep, ...
    bc6_labels,   time_full, temp_full, sep, ...
    bc10_labels,  time_full, p2atm_full, ...
    'VariableNames', {...
    'Input_for_FEAR',   'time_s_1', 'Hr',             'radiative_heating', ...
    'rho_u_CH0',        'pressure_atm_postshock', 'blowing_correction', 'sep1', ...
    'Input_for_FEAR_2', 'time_s_2', 'temperature_K',  'sep2', ...
    'Input_for_FEAR_3', 'time_s_3', 'pressure2_atm_postshock'});

% Write FEAR input to separate sheet
writetable(fear_table, filename, "Sheet", "FEAR_Input");

disp("Done. Written to " + filename);
disp("  Sheet 1: original data + freestream p, shock ratio, post-shock p");
disp("  Sheet 'FEAR_Input': FEAR blocks with post-normal-shock pressure");