%% Cramer-von Mises comparison of basic and refined generators
clear; close all; clc;
N = 8;
numSamples = 1e6;
numHeadRefinements = 2;
numTailRefinements = 4;
config = struct('numGridPoints',65537,'testRange',[-8,8]);

% Case A: the unrefined N=8 table.
rng(1,'twister');
basicTable = build_tables(N);
basicSamples = trapzig_randn(numSamples,basicTable);
basicResult = cramer_von_mises_test(basicSamples,config);
printCvmResult('Basic N=8',basicResult);

% Case B: two recursive head tables and four recursive tail tables.
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
refinedResult = cramer_von_mises_test(refinedSamples,config);
printCvmResult('Refined N=8, H=2, T=4',refinedResult);

% The first and last grid edges are infinite. Plot the finite grid only.
figure('Color','w');
plot(refinedResult.xGrid,refinedResult.empiricalCDF(2:end-1), ...
    'b-','LineWidth',1.2); hold on;
plot(refinedResult.xGrid,refinedResult.idealCDF(2:end-1), ...
    'r--','LineWidth',1.2);
grid on; xlabel('x'); ylabel('CDF');
title('Refined trapezoidal sampler versus standard normal CDF');
legend('Empirical CDF','Ideal N(0,1) CDF','Location','best');

function printCvmResult(label,result)
    fprintf('\n%s: samples=%d, CvM=%.10g, critical=%.5f\n', ...
        label,result.sampleCount,result.statistic,result.criticalValue);
    if result.reject
        fprintf('%s: reject H0 (X follows N(0,1)).\n',label);
    else
        fprintf('%s: fail to reject H0 (X follows N(0,1)).\n',label);
    end
end
