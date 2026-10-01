%% Classical Ziggurat method for standard Gaussian random variables
% This is an intentionally direct, educational implementation.  It uses
% floating-point arithmetic and scalar rejection sampling so that the code
% follows the geometry of the method closely.

clear;
close all;
clc;

Nsample = 1e6;
Nlayer  = 128;

% R is the point where the rectangular part of the bottom layer ends and
% the separately sampled Gaussian tail begins.  This value is the classical
% boundary for the 128-layer normal Ziggurat.
R = 3.442619855899;

% x and y describe the right and upper boundaries of the horizontal layers.
% The table is constructed using the unnormalized density exp(-x^2/2).
[x, y, A, tail] = build_ziggurat(Nlayer, R);

% A fixed seed makes the Ziggurat result repeatable.  This generator call
% uses only rand; randn appears below solely as an independent benchmark.
rng(1, 'twister');
samples = ziggurat_gaussian(x, y, R, Nsample);

% Generate an equally large reference data set with MATLAB's built-in
% Gaussian generator.  randn is used only for this comparison, never by the
% Ziggurat generator above.
rng(2, 'twister');
builtinSamples = randn(Nsample, 1);

zigguratMean = mean(samples);
zigguratVariance = var(samples);
zigguratStd = std(samples);
builtinMean = mean(builtinSamples);
builtinVariance = var(builtinSamples);
builtinStd = std(builtinSamples);

fprintf('Number of samples:       %d\n', Nsample);
fprintf('Number of layers:        %d\n', Nlayer);
fprintf('Equal layer area A:      %.15g\n', A);
fprintf('Positive tail area:      %.15g\n', tail);
fprintf('\nComparison with MATLAB randn (using %d samples each):\n', Nsample);
comparisonTable = table( ...
    [zigguratMean; builtinMean], ...
    [zigguratVariance; builtinVariance], ...
    [zigguratStd; builtinStd], ...
    'VariableNames', {'Mean', 'Variance', 'StandardDeviation'}, ...
    'RowNames', {'EducationalZiggurat', 'MATLAB_randn'});
disp(comparisonTable);

%% Compare the Ziggurat histogram with MATLAB's built-in Gaussian generator
figure('Color', 'w');
histogram(samples, 120, 'Normalization', 'pdf', ...
    'FaceColor', [0.35 0.65 0.85], 'EdgeColor', 'none');
hold on;
xplot = linspace(-5, 5, 1000);

% Use the mean and standard deviation measured from the randn reference
% sample to draw its corresponding Gaussian PDF.  Writing the formula
% explicitly avoids requiring the Statistics and Machine Learning Toolbox.
builtinPDF = exp(-0.5*((xplot-builtinMean)/builtinStd).^2) ...
    / (builtinStd*sqrt(2*pi));
plot(xplot, builtinPDF, 'r-', 'LineWidth', 2);
grid on;
xlabel('x');
ylabel('Probability density');
title(sprintf('Educational Ziggurat versus MATLAB randn (%d samples each)', ...
    Nsample));
legend('Ziggurat histogram', 'PDF fitted to MATLAB randn sample', ...
    'Location', 'best');
xlim([-5 5]);

%% Show the positive-half Gaussian and the Ziggurat rectangles
figure('Color', 'w');
xcurve = linspace(0, 4.5, 1200);
plot(xcurve, exp(-xcurve.^2/2), 'k-', 'LineWidth', 2);
hold on;

% Bottom rectangle.  Its missing area A - R*f(R) is exactly the tail area.
rectangle('Position', [0, 0, R, y(1)], ...
    'EdgeColor', [0.15 0.45 0.80], 'LineWidth', 0.6);

% For layer i, the proposal rectangle spans y(i-1) to y(i) and has width
% x(i-1).  Its area is x(i-1)*(y(i)-y(i-1)) = A.
for i = 2:Nlayer
    rectangle('Position', [0, y(i-1), x(i-1), y(i)-y(i-1)], ...
        'EdgeColor', [0.15 0.45 0.80], 'LineWidth', 0.6);
end

xline(R, '--r', 'R (tail boundary)', 'LabelVerticalAlignment', 'bottom');
grid on;
xlabel('Positive magnitude x');
ylabel('f(x) = exp(-x^2/2)');
title(sprintf('Positive-half Gaussian Ziggurat (%d equal-area layers)', Nlayer));
xlim([0 4.5]);
ylim([0 1.02]);
hold off;


function [x, y, A, tail] = build_ziggurat(N, R)
%BUILD_ZIGGURAT Construct the boundaries of a Gaussian Ziggurat.
%
% f(x) = exp(-x^2/2) is deliberately left unnormalized.  Normalization is
% unnecessary for rejection sampling because only relative heights matter.
%
% R is the beginning of the positive Gaussian tail.  The bottom layer is
% the rectangle R-by-f(R), together with the curved tail beyond R.
%
% A is the area assigned to every layer:
%       A = R*f(R) + integral_R^infinity f(t) dt.
% Equal areas are important: they let us choose a layer uniformly rather
% than maintaining a separate probability table for the layers.
%
% x(i) is the right boundary at height y(i), and y(i)=f(x(i)).  Thus the
% entries walk inward from (R,f(R)) to approximately (0,1).

    f = @(z) exp(-z.^2/2);

    tail = integral(f, R, Inf);
    A = R*f(R) + tail;

    x = zeros(1, N);
    y = zeros(1, N);
    x(1) = R;
    y(1) = f(R);

    for i = 2:N
        y(i) = y(i-1) + A/x(i-1);

        % Roundoff in the classical constants can put the last value a few
        % ulps above 1.  Clipping only protects log from that harmless error.
        y(i) = min(y(i), 1);
        x(i) = sqrt(-2*log(y(i)));
    end
end


function samples = ziggurat_gaussian(x, y, R, Nsample)
%ZIGGURAT_GAUSSIAN Draw standard-normal samples without using randn.
%
% Each pass first chooses one of the equal-area layers uniformly.  A rejected
% boundary point restarts the whole pass (including the layer selection).
% This detail preserves the correct relative probability of the layers.

    Nlayer = numel(x);
    samples = zeros(Nsample, 1);

    % The bottom layer contains a rectangle plus the tail.  Their areas add
    % to A, so this ratio selects the two pieces in proportion to area.
    fR = exp(-R^2/2);
    tailArea = integral(@(z) exp(-z.^2/2), R, Inf);
    rectangleArea = R*fR;
    bottomArea = rectangleArea + tailArea;

    for n = 1:Nsample
        accepted = false;

        while ~accepted
            layer = randi(Nlayer);

            if layer == 1
                if rand() < rectangleArea/bottomArea
                    % Uniform point in the rectangular part of layer 1.
                    magnitude = R*rand();
                else
                    % Beyond R, a finite rectangle cannot cover the Gaussian.
                    % Exponential rejection sampling handles this tail.  The
                    % accepted magnitude is R plus the exponential offset.
                    tailAccepted = false;
                    while ~tailAccepted
                        xtail = -log(rand())/R;
                        ytail = -log(rand());
                        tailAccepted = (2*ytail > xtail^2);
                    end
                    magnitude = R + xtail;
                end
                accepted = true;
            else
                % Draw uniformly across this layer's proposal rectangle.
                candidate = x(layer-1)*rand();

                if candidate <= x(layer)
                    % Everything left of x(layer) is guaranteed to lie below
                    % the Gaussian curve.  This fast path avoids calling exp.
                    magnitude = candidate;
                    accepted = true;
                else
                    % In the narrow boundary strip, draw a vertical coordinate
                    % and explicitly test whether the point is under f(x).
                    candidateY = y(layer-1) + ...
                        (y(layer)-y(layer-1))*rand();
                    if candidateY <= exp(-candidate^2/2)
                        magnitude = candidate;
                        accepted = true;
                    end
                    % Otherwise reject and choose a fresh layer.
                end
            end
        end

        % Reflect the accepted positive magnitude about zero with probability
        % 1/2 to obtain the full symmetric standard-normal distribution.
        if rand() < 0.5
            samples(n) = -magnitude;
        else
            samples(n) = magnitude;
        end
    end
end
