%% Phase 1 floating-point trapezoidal Gaussian reference
clear; close all; clc;
N = 8;
numSamples = 1e6;
table = build_tables(N);
fprintf(' i             a             w             d             l             u\n');
disp([(1:N)', table.a(:), table.w(:), table.d(:), table.l(:), table.u(:)]);
samples = trapzig_randn(numSamples, table);
assert(isreal(samples) && all(isfinite(samples)));
assert(all(table.a >= 0 & table.a <= 1));
assert(all(table.w >= 0 & table.d >= 0 & table.l >= table.u));
fprintf('Generated %d finite real samples; table constraints passed.\n', numSamples);
figure('Color','w');
histogram(samples,120,'Normalization','pdf','EdgeColor','none'); hold on;
xx = linspace(-5,5,1000);
plot(xx,exp(-xx.^2/2)/sqrt(2*pi),'r-','LineWidth',2);
grid on; xlabel('x'); ylabel('Density');
title(sprintf('Phase 1 trapezoidal sampler, N=%d, samples=%d',N,numSamples));
legend('Generated samples','Ideal standard Gaussian PDF','Location','best');
