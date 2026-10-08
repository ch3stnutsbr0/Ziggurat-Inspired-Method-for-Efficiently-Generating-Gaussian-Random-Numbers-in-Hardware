%% Phase 2 recursive head and tail trapezoidal Gaussian reference
clear; close all; clc;
N = 8;
numHeadRefinements = 2;
numTailRefinements = 4;
numSamples = 1e6;

tables.main = build_tables(N);
tables.head = cell(1, numHeadRefinements);
tables.tail = cell(1, numTailRefinements);

for level = 1:numHeadRefinements
    if level == 1
        parent = tables.main;
    else
        parent = tables.head{level-1};
    end
    tables.head{level} = build_recursive_table(parent, 'head');
end

for level = 1:numTailRefinements
    if level == 1
        parent = tables.main;
    else
        parent = tables.tail{level-1};
    end
    tables.tail{level} = build_recursive_table(parent, 'tail');
end

fprintf('Main table: %d entries, x=[%.8g, %.8g], y=[%.8g, %.8g]\n', ...
    N, tables.main.x(1), tables.main.x(end), ...
    tables.main.y(1), tables.main.y(end));
fprintf('Generated %d head tables and %d tail tables.\n', ...
    numel(tables.head), numel(tables.tail));

for level = 1:numel(tables.head)
    t = tables.head{level};
    fprintf('Head %d: parent x=[%.8g, %.8g], y=[%.8g, %.8g]; ', ...
        level, t.parentX(1), t.parentX(2), t.parentY(1), t.parentY(2));
    fprintf('next head x=[%.8g, %.8g]\n', t.x(1), t.x(2));
end

for level = 1:numel(tables.tail)
    t = tables.tail{level};
    fprintf('Tail %d: parent x=[%.8g, %.8g], y=[%.8g, %.8g]; ', ...
        level, t.parentX(1), t.parentX(2), t.parentY(1), t.parentY(2));
    fprintf('maximum realizable positive output = %.8g\n', max(t.l));
end

if isempty(tables.tail)
    maxPositiveOutput = max(tables.main.l);
else
    maxPositiveOutput = max(tables.tail{end}.l);
end
fprintf('Final maximum realizable positive output = %.8g\n', maxPositiveOutput);

samples = trapzig_randn(numSamples, tables);
assert(isreal(samples) && all(isfinite(samples)));
fprintf('All %d samples are finite and real.\n', numSamples);
fprintf('mean = %.8g, variance = %.8g, min = %.8g, max = %.8g\n', ...
    mean(samples), var(samples), min(samples), max(samples));

figure('Color','w');
histogram(samples, 120, 'Normalization','pdf', 'EdgeColor','none');
hold on;
xx = linspace(-5.5, 5.5, 1000);
plot(xx, normpdf(xx,0,1), 'r-', 'LineWidth',2);
grid on; xlabel('x'); ylabel('Density');
title(sprintf('Recursive trapezoidal sampler, N=%d, head=%d, tail=%d', ...
    N, numHeadRefinements, numTailRefinements));
legend('Generated samples','Ideal standard Gaussian PDF','Location','best');
