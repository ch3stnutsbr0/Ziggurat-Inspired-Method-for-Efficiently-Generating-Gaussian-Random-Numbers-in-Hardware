function magnitude = sample_table(numSamples, table)
%SAMPLE_TABLE Draw nonnegative values from the tabulated trapezoids.
    magnitude = zeros(numSamples,1);
    for n = 1:numSamples
        i = randi(table.N);
        if rand < table.a(i)
            magnitude(n) = table.w(i)*rand;
        else
            % The triangular wedge has width d at its wide edge. For a
            % uniform point in a triangle, height fraction is sqrt(U).
            magnitude(n) = table.w(i) + table.d(i)*sqrt(rand)*rand;
        end
    end
end
