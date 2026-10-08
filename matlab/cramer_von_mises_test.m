function result = cramer_von_mises_test(samples, config)
%CRAMER_VON_MISES_TEST Paper Eq. (24) against a known N(0,1) target.
% The paper used one point per possible fixed-point output. This floating-
% point reference instead uses a dense grid (default 65537 points) on
% [-8,8]. The grid is extended to -Inf and Inf for CDF normalization.
% The statistic uses the paper's left-grid-point sum:
% n*sum((Fn(i)-F(i))^2 * (F(i+1)-F(i))). No parameters are fitted.
%
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

    % The outer bins retain observations beyond [-8,8]. Cumulative counts
    % give Fn at every edge in O(n+m), including Fn(-Inf)=0 and Fn(Inf)=1.
    binCounts = histcounts(samples,gridEdges);
    empiricalCDF = [0, cumsum(binCounts)] ./ sampleCount;
    idealCDF = normcdf(gridEdges,0,1);
    cdfIncrements = diff(idealCDF);
    statistic = sampleCount * sum( ...
        (empiricalCDF(1:end-1)-idealCDF(1:end-1)).^2 ...
        .* cdfIncrements);

    assert(sum(binCounts)==sampleCount);
    assert(all(diff(empiricalCDF)>=0) && empiricalCDF(end)==1);
    assert(all(diff(idealCDF)>=0) && idealCDF(1)==0 && idealCDF(end)==1);
    assert(isfinite(statistic) && statistic>=0);

    % Section IV-B reports this asymptotic 95% critical threshold. It is a
    % critical-value decision; no CvM p-value is estimated here.
    criticalValue = 0.46136;
    result = struct('statistic',statistic, ...
        'criticalValue',criticalValue, ...
        'reject',statistic>criticalValue, ...
        'sampleCount',sampleCount, ...
        'method','Paper Eq. (24), floating-point left-grid sum', ...
        'xGrid',xGrid, ...
        'gridEdges',gridEdges, ...
        'empiricalCDF',empiricalCDF, ...
        'idealCDF',idealCDF, ...
        'binCounts',binCounts);
end
