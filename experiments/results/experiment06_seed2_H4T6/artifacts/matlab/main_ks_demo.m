%% Kolmogorov-Smirnov comparison of basic and refined generators
clear; clc;
N = 8;
numSamples = 1e6;
numHeadRefinements = 2;
numTailRefinements = 4;

rng(1,'twister');
basicTable = build_tables(N);
basicSamples = trapzig_randn(numSamples,basicTable);
basicResult = kolmogorov_smirnov_test(basicSamples);
printKsResult('Basic N=8',basicResult);

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
refinedResult = kolmogorov_smirnov_test(refinedSamples);
printKsResult('Refined N=8, H=2, T=4',refinedResult);

function printKsResult(label,result)
    fprintf('\n%s: samples=%d, D+=%.10g, D-=%.10g, D=%.10g, critical=%.10g\n', ...
        label,result.sampleCount,result.Dplus,result.Dminus, ...
        result.D,result.criticalValue);
    if result.reject
        fprintf('%s: reject H0 (X follows N(0,1)) at alpha=%.2f.\n', ...
            label,result.alpha);
    else
        fprintf('%s: fail to reject H0 (X follows N(0,1)) at alpha=%.2f.\n', ...
            label,result.alpha);
    end
end
