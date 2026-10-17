function result = chi_square_test(samples, config)
%CHI_SQUARE_TEST Pearson test against the known standard normal N(0,1).
% Section IV-A, Eq. (22): X^2=sum((observed-n*p)^2/(n*p)). This floating-
% point reference starts with 512 equal-width bins on [-8,8], as discussed
% in that section; it is not the paper's 2^16-bin fixed-point experiment.
% The first and last edges become -Inf and Inf so no samples or Gaussian
% tail probability are discarded. Adjacent bins are merged whenever their
% expected count is below the configured threshold (default 5).
%
% config fields (all optional): numBins, testRange, minExpectedCount, alpha.
    if nargin < 2 || isempty(config)
        config = struct();
    end
    if ~isstruct(config) || ~isscalar(config)
        error('config must be a scalar struct.');
    end
    if ~isnumeric(samples) || ~isvector(samples) || isempty(samples) || ...
            ~isreal(samples) || any(~isfinite(samples(:)))
        error('samples must be a nonempty vector of finite real numbers.');
    end

    numBins = 512;
    testRange = [-8, 8];
    minExpectedCount = 5;
    alpha = 0.05;
    if isfield(config, 'numBins'), numBins = config.numBins; end
    if isfield(config, 'testRange'), testRange = config.testRange; end
    if isfield(config, 'minExpectedCount')
        minExpectedCount = config.minExpectedCount;
    end
    if isfield(config, 'alpha'), alpha = config.alpha; end
    validateattributes(numBins, {'numeric'}, {'scalar','integer','>=',2});
    validateattributes(testRange, {'numeric'}, {'vector','numel',2,'finite'});
    if testRange(2) <= testRange(1)
        error('testRange must be increasing.');
    end
    validateattributes(minExpectedCount, {'numeric'}, {'scalar','positive','finite'});
    validateattributes(alpha, {'numeric'}, {'scalar','>',0,'<',1});

    n = numel(samples);
    if n < 2*minExpectedCount
        error('At least two bins with sufficient expected count are required.');
    end

    binEdges = linspace(testRange(1), testRange(2), numBins+1);
    binEdges(1) = -Inf;
    binEdges(end) = Inf;
    observedCounts = histcounts(samples, binEdges);
    probabilities = diff(normcdf(binEdges, 0, 1));
    expectedCounts = n.*probabilities;

    % Walk from left to right. A deficient bin joins its immediate right
    % neighbor; a deficient final bin joins its left neighbor. Removing the
    % shared edge keeps the merged counts tied to contiguous intervals.
    bin = 1;
    while bin <= numel(expectedCounts)
        if expectedCounts(bin) >= minExpectedCount
            bin = bin + 1;
        elseif bin < numel(expectedCounts)
            expectedCounts(bin+1) = expectedCounts(bin+1) + expectedCounts(bin);
            observedCounts(bin+1) = observedCounts(bin+1) + observedCounts(bin);
            expectedCounts(bin) = [];
            observedCounts(bin) = [];
            binEdges(bin+1) = [];
        elseif bin > 1
            expectedCounts(bin-1) = expectedCounts(bin-1) + expectedCounts(bin);
            observedCounts(bin-1) = observedCounts(bin-1) + observedCounts(bin);
            expectedCounts(bin) = [];
            observedCounts(bin) = [];
            binEdges(bin) = [];
            bin = bin - 1;
        else
            error('Cannot form bins with the requested minimum expected count.');
        end
    end

    r = numel(expectedCounts);
    if r < 2
        error('Fewer than two valid bins remain after expected-count merging.');
    end
    assert(all(expectedCounts >= minExpectedCount));
    assert(sum(observedCounts) == n);
    assert(abs(sum(expectedCounts)-n) <= 1e-10*n);

    statistic = sum((observedCounts-expectedCounts).^2 ./ expectedCounts);
    degreesOfFreedom = r - 1; % Mean and variance were not fitted to samples.
    pValue = 1 - chi2cdf(statistic, degreesOfFreedom);
    % The paper's "p value 0.95" describes a 95% critical threshold.
    % Conventional significance testing rejects when the upper-tail p<0.05.
    reject = pValue < alpha;

    result = struct('statistic',statistic, ...
        'degreesOfFreedom',degreesOfFreedom, ...
        'pValue',pValue,'reject',reject, ...
        'observedCounts',observedCounts, ...
        'expectedCounts',expectedCounts, ...
        'binEdges',binEdges, ...
        'finalBinCount',r,'initialBinCount',numBins, ...
        'numSamples',n,'alpha',alpha, ...
        'minExpectedCount',minExpectedCount, ...
        'expectedProbabilities',expectedCounts./n);
end
