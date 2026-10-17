function result = anderson_darling_test(samples, config)
%ANDERSON_DARLING_TEST Paper Section IV-C, known standard-normal target.
% The paper sums over fixed-point outputs. This floating-point adaptation
% uses a dense grid on [-8,8] and two outer bins reaching +/-Inf.
% Equation (25) gives the weight 1/(F*(1-F)). The printed denominator in
% Equation (26) appears inconsistent with (25); use the integral's weight.
% Optional config fields: numGridPoints, testRange.
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

    numGridPoints = 65537;
    testRange = [-8, 8];
    if isfield(config,'numGridPoints')
        numGridPoints = config.numGridPoints;
    end
    if isfield(config,'testRange')
        testRange = config.testRange;
    end
    validateattributes(numGridPoints,{'numeric'}, ...
        {'scalar','integer','>=',3});
    validateattributes(testRange,{'numeric'}, ...
        {'vector','numel',2,'finite'});
    if testRange(2) <= testRange(1)
        error('testRange must be increasing.');
    end

    sampleCount = numel(samples);
    xGrid = linspace(testRange(1),testRange(2),numGridPoints);
    gridEdges = [-Inf, xGrid, Inf];
    binCounts = histcounts(samples,gridEdges);
    empiricalCDF = [0, cumsum(binCounts)] ./ sampleCount;
    idealCDF = normcdf(gridEdges,0,1);
    cdfIncrements = diff(idealCDF);

    % Equation (26) is a left-grid Riemann sum. The first interval starts
    % at F(-Inf)=0, where its weight is undefined, so evaluate that one
    % interval at its finite right endpoint. All other intervals use the
    % left endpoint. Zero-mass intervals contribute nothing and are omitted.
    % No CDF value is clamped and every observation enters the empirical CDF.
    evaluationIndex = 1:numel(cdfIncrements);
    evaluationIndex(1) = 2;
    referenceAtGrid = idealCDF(evaluationIndex);
    empiricalAtGrid = empiricalCDF(evaluationIndex);
    positiveMass = cdfIncrements > 0;
    validWeight = referenceAtGrid > 0 & referenceAtGrid < 1;
    if any(positiveMass & ~validWeight)
        error('A positive-mass interval has an undefined AD weight.');
    end
    included = positiveMass & validWeight;
    weightedErrors = ((empiricalAtGrid(included) - ...
        referenceAtGrid(included)).^2 ./ ...
        (referenceAtGrid(included) .* ...
        (1-referenceAtGrid(included)))) .* cdfIncrements(included);
    statistic = sampleCount * sum(weightedErrors);

    assert(sum(binCounts)==sampleCount);
    assert(all(diff(empiricalCDF)>=0) && empiricalCDF(end)==1);
    assert(all(diff(idealCDF)>=0) && idealCDF(1)==0 && idealCDF(end)==1);
    assert(isfinite(statistic) && statistic>=0);

    % Paper's asymptotic 95%% cutoff for a completely known reference CDF.
    criticalValue = 2.492;
    result = struct('statistic',statistic, ...
        'criticalValue',criticalValue, ...
        'reject',statistic>criticalValue, ...
        'sampleCount',sampleCount, ...
        'method','Paper Eq. (25) weighted floating-point grid sum', ...
        'xGrid',xGrid, ...
        'gridEdges',gridEdges, ...
        'binCounts',binCounts, ...
        'empiricalCDF',empiricalCDF, ...
        'idealCDF',idealCDF);
end
