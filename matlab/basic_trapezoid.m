%% Trapezoidal Ziggurat approximation for Gaussian RNG
clear;
close all;
clc;

Nsample = 1e6;
N = 128;
Nlayer = N;
headRefineLevels = 1;
headRefineN = N;
useHeadRefinement = true;

R = 3.442619855899;

[x, y, A, tail] = build_ziggurat(N, R);
headTable = build_head_table(x, y, headRefineLevels, headRefineN);

rng(1, 'twister');

% Run a baseline and a refined run with the same sample count.
rng(1, 'twister');
baselineSamples = trapezoid_gaussian(x, y, R, Nsample, [], false);
rng(1, 'twister');
[samples, refinedCount] = trapezoid_gaussian(x, y, R, Nsample, headTable, useHeadRefinement);

%% MATLAB reference
rng(2, 'twister');
builtinSamples = randn(Nsample,1);

fprintf('Number of samples  = %d\n', Nsample);
fprintf('Number of layers   = %d\n', N);
fprintf('Head refinement    = %d levels, %d subdivisions per level\n', headRefineLevels, headRefineN);
fprintf('Baseline mean      = %.8f; variance = %.8f\n', mean(baselineSamples), var(baselineSamples));
fprintf('Refined mean       = %.8f; variance = %.8f\n', mean(samples), var(samples));
fprintf('Head path fraction = %.6f (nominal probability %.6f)\n', refinedCount/Nsample, 1/N);

fprintf('\nMATLAB mean        = %.8f\n', mean(builtinSamples));
fprintf('MATLAB variance    = %.8f\n', var(builtinSamples));
fprintf('MATLAB std         = %.8f\n', std(builtinSamples));

%% Histogram
figure('Color','w');

histogram(baselineSamples, 150, ...
    'Normalization','pdf', ...
    'EdgeColor','none', 'FaceAlpha', 0.45);
hold on;
histogram(samples, 150, 'Normalization','pdf', ...
    'EdgeColor','none', 'FaceAlpha', 0.45);

hold on;

xx = linspace(-5,5,1500);

truePDF = exp(-xx.^2/2)/sqrt(2*pi);

plot(xx,truePDF,'k-','LineWidth',2);

xlabel('x');
ylabel('Probability density');
title('Baseline and recursively refined-head trapezoidal Ziggurat');
legend('Baseline','Refined head','True Gaussian');
grid on;
xlim([-5 5]);


%% Error plot
figure('Color','w');

[counts,edges] = histcounts(samples,300,...
    'Normalization','pdf');

centers = (edges(1:end-1)+edges(2:end))/2;

trueAtBins = exp(-centers.^2/2)/sqrt(2*pi);

plot(centers, counts-trueAtBins);

xlabel('x');
ylabel('PDF error');
title('Trapezoidal approximation error');
grid on;
xlim([-4 4]);

%% Head geometry and error diagnostics
figure('Color','w');
xxh = linspace(0, x(end-1), 1200);
fh = exp(-xxh.^2/2);
plot(xxh, fh, 'k-', 'LineWidth', 2); hold on;
plot([0 x(end-1)], [y(end) y(end-1)], 'r--', 'LineWidth', 1.8);
for k = 1:numel(headTable(1).xBounds)-1
    xb = headTable(1).xBounds(k:k+1);
    yb = headTable(1).yBounds(k:k+1);
    plot(xb, yb, 'b-', 'LineWidth', 1.1);
end
grid on; xlabel('Positive magnitude x'); ylabel('f(x) = exp(-x^2/2)');
title('Gaussian head: coarse segment and equal-probability refined segments');
legend('True Gaussian','Original coarse head','Refined head segments','Location','best');

figure('Color','w');
coarseLine = y(end) + (y(end-1)-y(end))*xxh/x(end-1);
[plotBounds, plotHeights] = composite_head_bounds(headTable);
refinedLine = interp1(plotBounds, plotHeights, xxh, 'linear');
plot(xxh, abs(coarseLine-fh), 'r--', 'LineWidth', 1.5); hold on;
plot(xxh, abs(refinedLine-fh), 'b-', 'LineWidth', 1.5);
grid on; xlabel('Positive magnitude x'); ylabel('Absolute PDF-shape error');
title(sprintf('Head approximation error (max coarse %.3g, refined %.3g)', ...
    max(abs(coarseLine-fh)), max(abs(refinedLine-fh))));
legend('Coarse head','Refined head','Location','best');

%% Error by requested recursive depth (table construction only)
levelError = zeros(3,1);
for lev = 0:2
    tab = build_head_table(x, y, lev, headRefineN);
    if lev == 0
        approx = coarseLine;
    else
        [tb,ty] = composite_head_bounds(tab);
        approx = interp1(tb, ty, xxh, 'linear');
    end
    levelError(lev+1) = sqrt(mean((approx-fh).^2));
end

function [bounds,heights] = composite_head_bounds(table)
% Join outer-level segments to the recursively refined zero-adjacent segment.
    bounds = table(end).xBounds;
    heights = table(end).yBounds;
    for level = numel(table)-1:-1:1
        bounds = [bounds, table(level).xBounds(3:end)]; %#ok<AGROW>
        heights = [heights, table(level).yBounds(3:end)]; %#ok<AGROW>
    end
end
fprintf('Head RMS shape error levels 0/1/2: %.6g, %.6g, %.6g\n', levelError);
fprintf('Head max abs shape error coarse/refined: %.6g / %.6g\n', ...
    max(abs(coarseLine-fh)), max(abs(refinedLine-fh)));


%% -------------------------------------------------------
function [x,y,A,tail] = build_ziggurat(N,R)

    f = @(z) exp(-z.^2/2);

    tail = integral(f,R,Inf);
    A = R*f(R) + tail;

    x = zeros(1,N);
    y = zeros(1,N);

    x(1) = R;
    y(1) = f(R);

    for i = 2:N

        y(i) = y(i-1) + A/x(i-1);

        y(i) = min(y(i),1);

        x(i) = sqrt(-2*log(y(i)));

    end
end


%% -------------------------------------------------------
function [samples,refinedCount] = trapezoid_gaussian(x,y,R,Nsample,headTable,useHeadRefinement)

    Nlayer = numel(x);

    samples = zeros(Nsample,1);
    refinedCount = 0;

    %% Bottom layer: keep classical implementation for now

    fR = exp(-R^2/2);

    tailArea = integral( ...
        @(z) exp(-z.^2/2), ...
        R,Inf);

    rectangleArea = R*fR;

    bottomArea = rectangleArea + tailArea;


    for n = 1:Nsample

        layer = randi(Nlayer);

        %% Bottom/tail: unchanged
        if layer == 1

            if rand() < rectangleArea/bottomArea

                magnitude = R*rand();

            else

                tailAccepted = false;

                while ~tailAccepted

                    xtail = -log(rand())/R;

                    ytail = -log(rand());

                    tailAccepted = ...
                        (2*ytail > xtail^2);

                end

                magnitude = R + xtail;

            end


        %% Ordinary layers: trapezoidal approximation
        elseif useHeadRefinement && layer == Nlayer && ~isempty(headTable)
            % Each CDF-quantile interval is equally probable under the true
            % Gaussian head mass. Only the final (innermost) interval is
            % recursively split; ordinary layers retain their original path.
            magnitude = sample_head(headTable, 1);
            refinedCount = refinedCount + 1;

        else

            wi = x(layer);

            di = x(layer-1) - x(layer);

            ai = wi / (wi + di/2);

            u0 = rand();

            if u0 < ai

                %% Rectangle
                u1 = rand();

                magnitude = wi*u1;

            else

                %% Triangle
                u1 = 2*rand()-1;
                u2 = 2*rand()-1;

                t = abs((u1+u2)/2);

                magnitude = ...
                    wi + di*t;

            end
        end


        %% Random sign

        if rand() < 0.5

            samples(n) = -magnitude;

        else

            samples(n) = magnitude;

        end

    end
end

function table = build_head_table(x,y,nLevels,nSub)
%BUILD_HEAD_TABLE Precompute equal-Gaussian-mass segments in the difficult head.
% The refinement shrinks the strongly curved region around zero instead of
% asking one straight segment to represent the entire head. Tables are fixed
% before generation, which maps naturally to a future ROM implementation.
    table = struct('xBounds',{},'yBounds',{},'slope',{},'intercept',{},'probability',{});
    if nLevels == 0, return; end
    left = 0;
    right = x(end-1);
    for level = 1:nLevels
        q = linspace(0,1,nSub+1);
        cLeft = 0.5 + 0.5*erf(left/sqrt(2));
        cRight = 0.5 + 0.5*erf(right/sqrt(2));
        bounds = sqrt(2)*erfinv(2*(cLeft + q*(cRight-cLeft))-1);
        bounds(1)=left; bounds(end)=right;
        heights = exp(-bounds.^2/2);
        table(level).xBounds = bounds;
        table(level).yBounds = heights;
        table(level).slope = diff(heights)./diff(bounds);
        table(level).intercept = heights(1:end-1)-table(level).slope.*bounds(1:end-1);
        table(level).probability = (cRight-cLeft)/nSub;
        left = bounds(1); right = bounds(2); % recurse into innermost (zero-adjacent) interval
    end
end

function x = sample_head(table,level)
% Select a subregion uniformly (the table has equal-probability CDF bins).
    idx = randi(numel(table(level).xBounds)-1);
    if level < numel(table) && idx == 1
        x = sample_head(table,level+1);
        return;
    end
    a = table(level).xBounds(idx); b = table(level).xBounds(idx+1);
    fa = table(level).yBounds(idx); fb = table(level).yBounds(idx+1);
    % Uniform-under-linear-boundary trapezoid: a rectangle plus the residual
    % triangle, sampled using the same rectangle/triangle decomposition.
    w = b-a; hmin = min(fa,fb); hdiff = abs(fb-fa);
    if rand() < (w*hmin)/(w*hmin + w*hdiff/2)
        x = a + w*rand();
    else
        % Uniform point in the residual triangle using barycentric weights.
        u = rand(); v = rand();
        if u+v > 1, u=1-u; v=1-v; end
        if fb >= fa
            x = a + w*(u+v);
        else
            x = a + w*(1-u-v);
        end
    end
end
