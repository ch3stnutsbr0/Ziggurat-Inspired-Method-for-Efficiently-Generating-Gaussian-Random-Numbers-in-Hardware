function magnitude = sample_recursive_table(numSamples, tables)
%SAMPLE_RECURSIVE_TABLE Follow the selected extreme until a leaf is reached.
% The main table can descend at entry 1 (head) or N (tail). Once inside a
% head table, only entry 1 descends; inside a tail table, only entry N does.
% Every final trapezoid is sampled by sample_table, with no curve test.
    magnitude = zeros(numSamples,1);
    for n = 1:numSamples
        current = tables.main;
        branch = 'main';
        level = 0;
        while true
            i = randi(current.N);
            if (strcmp(branch,'main') || strcmp(branch,'head')) && ...
                    i == 1 && level < numel(tables.head)
                level = level + 1;
                branch = 'head';
                current = tables.head{level};
            elseif (strcmp(branch,'main') || strcmp(branch,'tail')) && ...
                    i == current.N && level < numel(tables.tail)
                level = level + 1;
                branch = 'tail';
                current = tables.tail{level};
            else
                magnitude(n) = sample_table(1, current, i);
                break;
            end
        end
    end
end
