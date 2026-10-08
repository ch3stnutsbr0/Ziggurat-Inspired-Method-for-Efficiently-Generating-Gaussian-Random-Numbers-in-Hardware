function [l, u] = fit_trapezoid(yLow, yHigh)
%FIT_TRAPEZOID First-order orthonormal Legendre L2 approximation (III-B).
% Eq. (14) maps the density slice to t in [-1,1]. Since this implementation
% stores x_0=0,...,x_N=Inf (so y decreases with index), the local map is
% oriented from yLow at t=-1 to yHigh at t=1. This makes Ptilde(-1) the
% longer base as required by the paper's l/u geometry. The inverse curve is
% x(t)=sqrt(-2*log(sqrt(2*pi)*y(t))). Eqs. (15)-(17) give its orthonormal
% P0/P1 coefficients and the fitted line. l=Ptilde(-1) is the longer,
% lower-x base; u=Ptilde(1) is the shorter, upper-x base.
% On the final slice yLow=0, x(t) has an integrable logarithmic endpoint
% singularity. Substituting t=2*s^2-1 removes it from the quadrature.
    if ~(isscalar(yLow) && isscalar(yHigh) && isfinite(yLow) && ...
            isfinite(yHigh) && yLow >= 0 && yHigh > yLow)
        error('Require finite 0 <= yLow < yHigh.');
    end

    if yLow == 0
        % y=yHigh*s^2, t=2*s^2-1, dt=4*s*ds. This is the same Legendre
        % coefficient integral, including the true unbounded y=0 endpoint.
        xAtS = @(s) inverseGaussianForQuadrature(yHigh.*s.^2);
        lambda0 = integral(@(s) 4.*s.*xAtS(s)./sqrt(2), 0, 1, ...
            'ArrayValued', true, 'RelTol', 1e-10, 'AbsTol', 1e-12);
        lambda1 = integral(@(s) 4.*s.*(2.*s.^2-1).*xAtS(s).*sqrt(3/2), ...
            0, 1, 'ArrayValued', true, 'RelTol', 1e-10, 'AbsTol', 1e-12);
    else
        densityAtT = @(t) yLow + (yHigh-yLow).*((t+1)./2);
        xAtT = @(t) inverseGaussianForQuadrature(densityAtT(t));
        lambda0 = integral(@(t) xAtT(t)./sqrt(2), -1, 1, ...
            'ArrayValued', true, 'RelTol', 1e-10, 'AbsTol', 1e-12);
        lambda1 = integral(@(t) t.*xAtT(t).*sqrt(3/2), -1, 1, ...
            'ArrayValued', true, 'RelTol', 1e-10, 'AbsTol', 1e-12);
    end

    % Eq. (17): Ptilde(t)=lambda1*sqrt(3/2)*t+lambda0/sqrt(2).
    center = lambda0/sqrt(2);
    slope = lambda1*sqrt(3/2);
    endpointValues = [center-slope, center+slope];
    l = max(endpointValues);
    u = min(endpointValues);
end

function x = inverseGaussianForQuadrature(y)
% The infinite value at y=0 is confined to the single integration endpoint.
    x = zeros(size(y));
    interior = y > 0;
    x(interior) = sqrt(max(0, -2.*log(sqrt(2*pi).*y(interior))));
end
