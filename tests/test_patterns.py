import patterns

X = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
Y = ((0, 1, 0), (1, 0, 0), (0, 0, 1))


def test_row_becomes_one_pattern():
    items = [("beam.sldprt", X, (i * 500.0, 0.0, 0.0)) for i in range(4)]
    pats, singles = patterns.plan(items)
    assert singles == [] and len(pats) == 1
    p = pats[0]
    assert (p["n1"], p["s1"], p["n2"]) == (4, 500.0, 1) and sorted(p["members"]) == [0, 1, 2, 3]


def test_grid_becomes_two_direction_pattern():
    items = [("post.sldprt", X, (x * 100.0, 0.0, z * 250.0)) for z in range(3) for x in range(5)]
    pats, singles = patterns.plan(items)
    assert singles == [] and len(pats) == 1
    p = pats[0]
    assert (p["n1"], p["s1"], p["n2"], p["s2"]) == (5, 100.0, 3, 250.0)


def test_irregular_and_mixed_stay_apart():
    items = [("a.sldprt", X, (0.0, 0, 0)), ("a.sldprt", X, (100.0, 0, 0)), ("a.sldprt", X, (330.0, 0, 0)),
             ("b.sldprt", X, (200.0, 0, 0)), ("a.sldprt", Y, (400.0, 0, 0))]
    pats, singles = patterns.plan(items)
    covered = {k for p in pats for k in p["members"]}
    assert covered | set(singles) == set(range(len(items))) and not covered & set(singles)
    assert 3 in singles and 4 in singles          # other file / other orientation never join a pattern
