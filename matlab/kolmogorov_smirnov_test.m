function result = kolmogorov_smirnov_test(samples)
%KOLMOGOROV_SMIRNOV_TEST Paper Eq. (27), two-sided known-normal KS statistic.
% Sorting evaluates both sides of every empirical CDF jump exactly, so a
% fixed grid and MATLAB's kstest are unnecessary. No parameters are fitted.
    if ~isnumeric(samples) || ~isvector(samples) || isempty(samples) || ...
            ~isreal(samples) || any(~isfinite(samples(:)))
        error('samples must be a nonempty vector of finite real numbers.');
    end

    sortedSamples = sort(samples(:));
    sampleCount = numel(sortedSamples);
    idealCDF = normcdf(sortedSamples,0,1);
    sampleIndex = (1:sampleCount)';
    Dplus = max(sampleIndex./sampleCount - idealCDF);
    Dminus = max(idealCDF - (sampleIndex-1)./sampleCount);
    D = max(Dplus,Dminus);

    assert(isfinite(D) && D>=0 && D<=1);
    assert(Dplus>=0 && Dplus<=1 && Dminus>=0 && Dminus<=1);

    % Development-run approximation at alpha=0.05. The paper calculated a
    % more accurate cutoff at n=2^25 using Simard-L'Ecuyer's approach.
    alpha = 0.05;
    criticalValue = 1.36/sqrt(sampleCount);
    result = struct('D',D, ...
        'Dplus',Dplus, ...
        'Dminus',Dminus, ...
        'statistic',D, ...
        'criticalValue',criticalValue, ...
        'alpha',alpha, ...
        'reject',D>criticalValue, ...
        'sampleCount',sampleCount, ...
        'method','Exact empirical two-sided KS; asymptotic 5% cutoff');
end
