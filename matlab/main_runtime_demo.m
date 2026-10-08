%% Sampling-time comparison on this MATLAB installation
% Table construction is timed separately because it is offline work.
% These CPU timings compare the MATLAB reference implementations; they do
% not predict FPGA throughput. Each sampling run creates a column vector.
clear; clc;
N = 8;
numHeadRefinements = 2;
numTailRefinements = 4;
numSamples = 1e6;
numTrials = 3;
warmupSamples = 1e4;

setupTimer = tic;
basicTable = build_tables(N);
basicSetupSeconds = toc(setupTimer);

setupTimer = tic;
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
refinedSetupSeconds = toc(setupTimer);

% Warm up function dispatch and MATLAB's JIT before recording times.
rng(1,'twister');
trapzig_randn(warmupSamples,basicTable);
trapzig_randn(warmupSamples,tables);
randn(warmupSamples,1);

basicSeconds = zeros(numTrials,1);
refinedSeconds = zeros(numTrials,1);
builtinSeconds = zeros(numTrials,1);
for trial = 1:numTrials
    % Reset the stream outside each timed section. All methods receive the
    % same seed, and seeding time does not enter the measurements.
    rng(100+trial,'twister');
    timer = tic;
    generated = trapzig_randn(numSamples,basicTable);
    basicSeconds(trial) = toc(timer);
    assert(numel(generated)==numSamples);
    clear generated;

    rng(100+trial,'twister');
    timer = tic;
    generated = trapzig_randn(numSamples,tables);
    refinedSeconds(trial) = toc(timer);
    assert(numel(generated)==numSamples);
    clear generated;

    rng(100+trial,'twister');
    timer = tic;
    generated = randn(numSamples,1);
    builtinSeconds(trial) = toc(timer);
    assert(numel(generated)==numSamples);
    clear generated;
end

basicMedian = median(basicSeconds);
refinedMedian = median(refinedSeconds);
builtinMedian = median(builtinSeconds);
fprintf('N=%d, head=%d, tail=%d, samples/run=%d, trials=%d\n', ...
    N,numHeadRefinements,numTailRefinements,numSamples,numTrials);
fprintf('Offline table construction: basic %.6g s; refined %.6g s\n', ...
    basicSetupSeconds,refinedSetupSeconds);
fprintf('\n%-18s %14s %18s %18s\n', ...
    'Method','Median seconds','Samples/second','Time / randn time');
fprintf('%-18s %14.6g %18.6g %17.3fx\n', ...
    'Basic',basicMedian,numSamples/basicMedian,basicMedian/builtinMedian);
fprintf('%-18s %14.6g %18.6g %17.3fx\n', ...
    'Refined',refinedMedian,numSamples/refinedMedian,refinedMedian/builtinMedian);
fprintf('%-18s %14.6g %18.6g %17.3fx\n', ...
    'MATLAB randn',builtinMedian,numSamples/builtinMedian,1);
fprintf('\nIndividual trial times (basic, refined, randn), seconds:\n');
disp([basicSeconds, refinedSeconds, builtinSeconds]);
