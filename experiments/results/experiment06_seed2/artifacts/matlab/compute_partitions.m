function [x, y] = compute_partitions(N, xRange)
%COMPUTE_PARTITIONS Equal-area boundaries on the main or a parent slice.
% The printed Eq. (9) uses i/N, which conflicts with both x_0=0 and the
% standard-normal positive-half area 1/2. Following the explicitly stated
% increasing order x_0=0 < ... < x_N, we interpret its target as
% G(x_i)=(N-i)/(2N), where G(x)=x*f(x)+integral_x^Inf f(t)dt.
% For a recursive parent interval [xLeft,xRight], interpolate G between
% its two endpoints in N equal steps. Since G(x)=integral_0^f(x) f^{-1}(y)dy,
% equal steps divide the parent's ideal curved area equally.
% The main call keeps x_N=Inf and y_N=0; no tail cutoff is introduced.
    validateattributes(N, {'numeric'}, {'scalar','integer','positive'});
    if nargin < 2
        xRange = [0, Inf];
    end
    if ~(isnumeric(xRange) && numel(xRange)==2 && ...
            isfinite(xRange(1)) && xRange(1)>=0 && ...
            xRange(2)>xRange(1))
        error('xRange must be [xLeft,xRight] with 0<=xLeft<xRight.');
    end

    normalPdf = @(z) exp(-0.5.*z.^2)./sqrt(2*pi);
    G = @(z) gaussianArea(z, normalPdf);
    leftArea = G(xRange(1));
    rightArea = G(xRange(2));

    x = zeros(1, N+1);
    x(1) = xRange(1);

    % G is strictly decreasing for x>0, so each interior boundary is a
    % unique scalar root. Expand the bracket only for an infinite parent.
    for i = 1:N-1
        target = leftArea + (rightArea-leftArea)*i/N;
        lo = x(i);
        if isinf(xRange(2))
            hi = max(1, lo+1);
            while G(hi) > target
                hi = 2*hi;
            end
        else
            hi = xRange(2);
        end
        x(i+1) = fzero(@(z) G(z)-target, [lo, hi]);
    end

    x(N+1) = xRange(2);
    y = normpdf(x);
    if isinf(x(N+1))
        y(N+1) = 0;
    end
end

function area = gaussianArea(x, normalPdf)
    if isinf(x)
        area = 0;
    else
        area = x*normalPdf(x) + 0.5*erfc(x/sqrt(2));
    end
end
