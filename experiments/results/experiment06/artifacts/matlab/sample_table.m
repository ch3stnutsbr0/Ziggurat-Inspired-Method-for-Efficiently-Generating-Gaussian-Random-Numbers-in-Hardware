function magnitude = sample_table(numSamples, table, entries)
%SAMPLE_TABLE Draw nonnegative values from ordinary trapezoid entries.
% The optional scalar entry index lets recursion reuse this same geometry.
    magnitude = zeros(numSamples,1);
    for n = 1:numSamples
        if nargin < 3
            i = randi(table.N);
        else
            i = entries;
        end
        if rand < table.a(i)
            magnitude(n) = table.w(i)*rand;
        else
            % The rectangle spans [0,w_i]. The triangular extension spans
            % [w_i,w_i+d_i] and tapers to zero at its outer edge. |U1-U2|
            % has exactly that decreasing triangular density.
            u1 = rand;
            u2 = rand;
            magnitude(n) = table.w(i) + table.d(i)*abs(u1-u2);
            %magnitude(n) = table.w(i) + table.d(i)*abs((u1+u2)/2);
        end
    end
end
