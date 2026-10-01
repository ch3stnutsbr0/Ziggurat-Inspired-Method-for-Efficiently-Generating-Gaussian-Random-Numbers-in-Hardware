function [l, u] = fit_trapezoid(yLower, yUpper)
%FIT_TRAPEZOID First-order Legendre (L2) fit of x=f^{-1}(y) on a slice.
% Section III-B's linear fit on t in [-1,1] is c0*P0(t)+c1*P1(t).
% Orthogonality gives c0=integral(g)/2 and c1=3*integral(t*g)/2.
% The fitted values at the two ends are the horizontal trapezoid bases.
    if ~(isscalar(yLower) && isscalar(yUpper) && yLower >= 0 && yUpper > yLower)
        error('Require 0 <= yLower < yUpper.');
    end
    if yLower == 0
        error('A zero lower density has infinite inverse; use finite partition boundaries.');
    end
    midpoint = (yLower + yUpper)/2;
    halfWidth = (yUpper - yLower)/2;
    invDensity = @(yy) sqrt(max(0, -2*log(yy*sqrt(2*pi))));
    g = @(t) invDensity(midpoint + halfWidth.*t);
    c0 = 0.5 * integral(g, -1, 1, 'ArrayValued', true);
    c1 = 1.5 * integral(@(t) t.*g(t), -1, 1, 'ArrayValued', true);
    ends = [c0-c1, c0+c1];
    l = max(ends);
    u = min(ends);
end
