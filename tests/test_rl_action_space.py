import pytest

from rl.action_space import N_ACTIONS, action_to_fraction


def test_endpoints_map_to_zero_and_one():
    assert action_to_fraction(0) == 0.0
    assert action_to_fraction(N_ACTIONS - 1) == 1.0


def test_fractions_evenly_spaced():
    fractions = [action_to_fraction(a) for a in range(N_ACTIONS)]
    gaps = {round(b - a, 10) for a, b in zip(fractions, fractions[1:])}
    assert gaps == {round(1 / (N_ACTIONS - 1), 10)}


def test_rejects_out_of_range_action():
    with pytest.raises(ValueError):
        action_to_fraction(-1)
    with pytest.raises(ValueError):
        action_to_fraction(N_ACTIONS)
