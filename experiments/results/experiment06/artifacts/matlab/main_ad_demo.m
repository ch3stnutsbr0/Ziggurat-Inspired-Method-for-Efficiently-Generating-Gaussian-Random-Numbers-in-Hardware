%% Anderson-Darling comparison of basic and refined generators
clear; clc;
N = 8;
numSamples = 1e6;
numHeadRefinements = 2;
numTailRefinements = 4;
config = struct('numGridPoints',65537,'testRange',[-8,8]);

rng(1,'twister');
basicTable = build_tables(N);
basicSamples = trapzig_randn(numSamples,basicTable);
basicResult = anderson_darling_test(basicSamples,config);
printAdResult('Basic N=8',basicResult);

rng(1,'twister');
tables.main = build_tables(N);
tables.head = cell(1,numHeadRefinements);
tables.tail = cell(1,numTailRefinements);
for level = 1:numHeadRefinements
    if level == 1
        parent = tables.main;
    else
        parent = tables.head{level-1};
    end
    tables.head{level} = build_recursive_table(parent,'head');
end
for level = 1:numTailRefinements
    if level == 1
        parent = tables.main;
    else
        parent = tables.tail{level-1};
    end
    tables.tail{level} = build_recursive_table(parent,'tail');
end
refinedSamples = trapzig_randn(numSamples,tables);
refinedResult = anderson_darling_test(refinedSamples,config);
printAdResult('Refined N=8, H=2, T=4',refinedResult);

reduction = 100*(basicResult.statistic-refinedResult.statistic) ...
    /basicResult.statistic;
fprintf('AD statistic change after refinement: %.2f%%\n',reduction);
if refinedResult.statistic < basicResult.statistic
    fprintf('Refinement reduces the tail-weighted AD discrepancy.\n');
else
    fprintf('Refinement did not reduce AD on this sample.\n');
end

function printAdResult(label,result)
    fprintf('\n%s: samples=%d, AD=%.10g, critical=%.3f\n', ...
        label,result.sampleCount,result.statistic,result.criticalValue);
    if result.reject
        fprintf('%s: reject H0 (X follows N(0,1)).\n',label);
    else
        fprintf('%s: fail to reject H0 (X follows N(0,1)).\n',label);
    end
end
