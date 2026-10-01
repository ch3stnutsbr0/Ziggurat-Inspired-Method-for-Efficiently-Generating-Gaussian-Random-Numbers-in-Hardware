function table = build_tables(N)
%BUILD_TABLES Precompute trapezoid parameters for the Phase 1 sampler.
    [x, y] = compute_partitions(N);
    l = zeros(1,N); u = zeros(1,N);
    for i = 1:N
        [l(i),u(i)] = fit_trapezoid(y(i+1),y(i));
    end
    table = struct('N',N,'a',2*u./(u+l),'w',u,'d',l-u, ...
        'l',l,'u',u,'x',x,'y',y);
end
