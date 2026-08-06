"""Discretized action: what fraction of *remaining* inventory to trade
this step. Shared between rl/env.py (training) and rl/policy_algorithm.py
(evaluation/inference) so both interpret a trained model's action indices
identically.
"""

N_ACTIONS = 11  # fractions 0.0, 0.1, 0.2, ..., 1.0


def action_to_fraction(action: int, n_actions: int = N_ACTIONS) -> float:
    if not 0 <= action < n_actions:
        raise ValueError(f"action {action} out of range [0, {n_actions})")
    return action / (n_actions - 1)
