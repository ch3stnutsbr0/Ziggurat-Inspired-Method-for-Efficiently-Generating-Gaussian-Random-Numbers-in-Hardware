%% Pearson chi-square comparison with MATLAB's built-in Gaussian generator
clear; close all; clc;

seedProposed = 1; %seeding for our algorithm
seedBuiltin = 2; %seeding for builtin GRNG

N = 8;
numSamples = 2^25;


config = struct('numBins',512, 'testRange',[-8,8], ...
    'minExpectedCount',5, 'alpha',0.05);
rng(seedProposed,'twister');

% Case A: no recursive head or tail tables.
basicTable = build_tables(N);
basicSamples = trapzig_randn(numSamples, basicTable);
basicResult = chi_square_test(basicSamples, config);
printChiSquareResult('Basic N=8', basicResult);

% Case B: recursively split only the extreme parent at each level.
rng(seedProposed,'twister');
tables.main = build_tables(N);
tables.head = cell(1,2);
tables.tail = cell(1,4);
for level = 1:numel(tables.head)
    if level == 1
        parent = tables.main;
    else
        parent = tables.head{level-1};
    end
    tables.head{level} = build_recursive_table(parent,'head');
end
for level = 1:numel(tables.tail)
    if level == 1
        parent = tables.main;
    else
        parent = tables.tail{level-1};
    end
    tables.tail{level} = build_recursive_table(parent,'tail');
end
refinedSamples = trapzig_randn(numSamples, tables);
refinedResult = chi_square_test(refinedSamples, config);
printChiSquareResult('Refined N=8, H=2, T=4', refinedResult);

% External reference only: randn is never used by the proposed generator.
rng(seedBuiltin,'twister');
builtinSamples = randn(numSamples,1);
builtinResult = chi_square_test(builtinSamples, config);
printChiSquareResult('MATLAB randn', builtinResult);

% The bin edges are determined by the same expected N(0,1) counts in each
% case. Merged tail bins have unequal widths, so use bin index on the axis.
figure('Color','w');
plot(refinedResult.observedCounts, 'b-'); hold on;
plot(builtinResult.observedCounts, 'g-');
plot(refinedResult.expectedCounts, 'r-');
grid on; xlabel('Final bin index'); ylabel('Count');
title('Pearson chi-square bin counts: refined generator and MATLAB randn');
legend('Refined','MATLAB randn','Expected N(0,1)','Location','best');

function printChiSquareResult(label, result)
    fprintf('\n%s\n', label);
    fprintf('Samples: %d; final bins: %d\n', ...
        result.numSamples, result.finalBinCount);
    fprintf('Chi-square statistic: %.10g; df: %d; p-value: %.10g\n', ...
        result.statistic, result.degreesOfFreedom, result.pValue);
    fprintf('Expected count min/max: %.8g / %.8g\n', ...
        min(result.expectedCounts), max(result.expectedCounts));
    fprintf('Probability sum: %.12g; observed/expected sums: %.12g / %.12g\n', ...
        sum(result.expectedProbabilities), sum(result.observedCounts), ...
        sum(result.expectedCounts));
    if result.reject
        fprintf('%s: reject H0 at alpha=%.2f.\n', label, result.alpha);
    else
        fprintf('%s: fail to reject H0 at alpha=%.2f.\n', label, result.alpha);
    end
end
