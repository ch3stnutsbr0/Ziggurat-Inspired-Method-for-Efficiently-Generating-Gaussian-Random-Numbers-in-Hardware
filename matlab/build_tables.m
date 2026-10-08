function table = build_tables(N, xRange)
%BUILD_TABLES Precompute a main or recursive trapezoid lookup table.
    if nargin < 2
        [x, y] = compute_partitions(N);
    else
        [x, y] = compute_partitions(N, xRange);
    end
    l = zeros(1,N); u = zeros(1,N);
    for i = 1:N
        [l(i),u(i)] = fit_trapezoid(y(i+1),y(i));
    end
    table = struct('N',N,'a',2*u./(u+l),'w',u,'d',l-u, ...
        'l',l,'u',u,'x',x,'y',y);
    assert(all(isfinite([table.a,table.w,table.d,table.l,table.u])));
    assert(all(table.a >= 0 & table.a <= 1));
    assert(all(table.w >= 0 & table.d >= 0 & table.l >= table.u));
end
