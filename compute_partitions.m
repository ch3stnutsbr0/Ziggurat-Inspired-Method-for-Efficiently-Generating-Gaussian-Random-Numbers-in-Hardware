function [x, y] = compute_partitions(N)
%COMPUTE_PARTITIONS Equal-probability boundaries on the positive half-normal.
% The referenced manuscript was not attached in this task, so Eq. (9)'s
% indexing/normalization cannot be checked. We use N equal probability
% intervals conditional on X>=0, with finite outer cutoff p=1-1/(2N).
% This explicit cutoff keeps all trapezoids finite; replace this rule when
% the paper's exact Eq. (9) is available. x is ordered from outer to center.
    validateattributes(N, {'numeric'}, {'scalar','integer','positive'});
    p = linspace(1 - 1/(2*N), 0.5, N+1);
    xAscending = sqrt(2) .* erfinv(2*p - 1);
    x = fliplr(xAscending); % center to outer? reorder consistently below
    x = [0, fliplr(xAscending(1:end-1))];
    y = exp(-0.5*x.^2) ./ sqrt(2*pi);
end
