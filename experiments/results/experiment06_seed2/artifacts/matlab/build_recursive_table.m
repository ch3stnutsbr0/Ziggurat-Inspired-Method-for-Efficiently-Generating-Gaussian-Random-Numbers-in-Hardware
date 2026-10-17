function child = build_recursive_table(parent, side)
%BUILD_RECURSIVE_TABLE Split one extreme parent slice into N equal areas.
% MATLAB entry 1 is the head (near x=0); entry N is the tail. At each
% level only that same extreme child is eligible for further recursion.
    if strcmp(side, 'head')
        parentEntry = 1;
    elseif strcmp(side, 'tail')
        parentEntry = parent.N;
    else
        error('side must be ''head'' or ''tail''.');
    end

    parentX = parent.x(parentEntry:parentEntry+1);
    parentY = parent.y(parentEntry:parentEntry+1);
    child = build_tables(parent.N, parentX);
    child.side = side;
    child.parentX = parentX;
    child.parentY = parentY;
    if isfield(parent, 'level')
        child.level = parent.level + 1;
    else
        child.level = 1;
    end
end
