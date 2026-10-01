function samples = trapzig_randn(numSamples, table)
%TRAPZIG_RANDN Public Phase 1 symmetric trapezoid-table sampler.
    magnitude = sample_table(numSamples, table);
    signs = 2*(rand(numSamples,1) >= 0.5)-1;
    samples = signs .* magnitude;
end
