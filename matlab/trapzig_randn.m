function samples = trapzig_randn(numSamples, table)
%TRAPZIG_RANDN Symmetric sampler for a basic table or recursive table set.
    if isfield(table, 'main')
        magnitude = sample_recursive_table(numSamples, table);
    else
        magnitude = sample_table(numSamples, table);
    end
    signs = 2*(rand(numSamples,1) >= 0.5)-1;
    samples = signs .* magnitude;
end
