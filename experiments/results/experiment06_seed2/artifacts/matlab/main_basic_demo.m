%% Phase 1 floating-point trapezoidal Gaussian reference
clear; close all; clc;
N = 8;
numSamples = 1e6;
table = build_tables(N);
fprintf('Partition boundaries x_0 through x_N:\n');
disp(table.x(:));
fprintf('Density boundaries y_i = normpdf(x_i), including y_N=0:\n');
disp(table.y(:));
fprintf(' i             a             w             d             l             u\n');
disp([(1:N)', table.a(:), table.w(:), table.d(:), table.l(:), table.u(:)]);
maxTableOutput = max(table.l);
fprintf('Maximum realizable positive output (max l_i): %.10g\n', maxTableOutput);
paperTableIValue = 3.5109;
% if abs(maxTableOutput-paperTableIValue) > 0.01
%     warning(['N=8 maximum %.8g differs from paper Table I value %.4f. ', ...
%         'See the documented Eq. (9) convention and compare against Fig. 3.'], ...
%         maxTableOutput, paperTableIValue);
% end
samples = trapzig_randn(numSamples, table);
assert(isreal(samples) && all(isfinite(samples)));
assert(all(table.a >= 0 & table.a <= 1));
assert(all(table.w >= 0 & table.d >= 0 & table.l >= table.u));
fprintf('Generated %d finite real samples; table constraints passed.\n', numSamples);
fprintf('mean = %.8g, variance = %.8g, min = %.8g, max = %.8g\n', ...
    mean(samples), var(samples), min(samples), max(samples));
figure('Color','w');
histogram(samples,120,'Normalization','pdf','EdgeColor','none'); hold on;
xx = linspace(-5,5,1000);
plot(xx,normpdf(xx,0,1),'r-','LineWidth',2);
grid on; xlabel('x'); ylabel('Density');
title(sprintf('Phase 1 trapezoidal sampler, N=%d, samples=%d',N,numSamples));
legend('Generated samples','Ideal standard Gaussian PDF','Location','best');
