"""Gymnasium environment for training the DQN execution policy against
real historical episodes. Not used at evaluation/inference time
-- rl/policy_algorithm.py wraps a trained model as a
backtest.algorithm.ExecutionAlgorithm instead, so evaluation runs through
the exact same simulator/metrics every other algorithm in this project
does. This class exists purely to drive stable-baselines3's training
loop.

Requires gymnasium and stable-baselines3 (see requirements.txt) --
neither is a dependency of anything else in this project.
"""

from datetime import timedelta

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from backtest.book_history import BookHistoryReader
from backtest.fill_model import FillModel
from backtest.order import ChildOrder
from lob.features import RealizedVolTracker
from rl.action_space import N_ACTIONS, action_to_fraction
from rl.observation import OBSERVATION_DIM, build_observation
from rl.reward import step_reward


class ExecutionEnv(gym.Env):
    def __init__(
        self,
        book_history: BookHistoryReader,
        episode_windows: list,
        parent_quantity: float,
        side: str,
        n_steps: int,
        risk_aversion: float,
        sigma: float,
    ):
        super().__init__()
        if not episode_windows:
            raise ValueError("episode_windows must be non-empty")
        self.book_history = book_history
        self.episode_windows = episode_windows
        self.parent_quantity = parent_quantity
        self.side = side
        self.side_sign = 1 if side == "buy" else -1
        self.n_steps = n_steps
        self.risk_aversion = risk_aversion
        self.sigma = sigma

        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(OBSERVATION_DIM,), dtype=np.float32
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        window_idx = self.np_random.integers(len(self.episode_windows))
        self._window = self.episode_windows[window_idx]
        self._tau = (self._window.end_time - self._window.start_time).total_seconds() / self.n_steps
        self._step_idx = 0
        self._remaining = self.parent_quantity
        self._vol_tracker = RealizedVolTracker()
        self._fill_run = FillModel(temporary_impact_coef=0.0, permanent_impact_coef=0.0).new_run()

        arrival_book = self.book_history.book_at_or_before(self._window.start_time)
        self._arrival_price = arrival_book.mid_price()
        self._vol_tracker.update(self._arrival_price)

        obs = build_observation(
            arrival_book, remaining_fraction=1.0, time_fraction=0.0, realized_vol=self._vol_tracker.value()
        )
        return obs, {}

    def step(self, action):
        fraction = action_to_fraction(int(action))
        qty = min(self._remaining, fraction * self._remaining)
        step_timestamp = self._window.start_time + timedelta(seconds=self._tau * self._step_idx)
        book = self.book_history.book_at_or_before(step_timestamp)
        self._vol_tracker.update(book.mid_price())

        child = ChildOrder(timestamp=step_timestamp, quantity=qty, side=self.side)
        result = self._fill_run.execute(child, book)
        self._remaining -= sum(f.quantity for f in result.fills)

        self._step_idx += 1
        terminated = self._step_idx >= self.n_steps
        unfilled_at_terminal = max(self._remaining, 0.0) if terminated else 0.0
        end_price = None
        if terminated:
            end_price = self.book_history.book_at_or_before(self._window.end_time).mid_price()

        reward = step_reward(
            result.fills, self._arrival_price, self.side_sign, self._remaining,
            self.sigma, self._tau, self.risk_aversion,
            is_terminal=terminated, unfilled_at_terminal=unfilled_at_terminal, end_price=end_price,
        )

        if not terminated:
            next_timestamp = self._window.start_time + timedelta(seconds=self._tau * self._step_idx)
            next_book = self.book_history.book_at_or_before(next_timestamp)
        else:
            next_book = book
        remaining_fraction = self._remaining / self.parent_quantity if self.parent_quantity > 0 else 0.0
        time_fraction = self._step_idx / self.n_steps
        obs = build_observation(next_book, remaining_fraction, time_fraction, self._vol_tracker.value())

        info = {"unfilled": result.unfilled_quantity, "n_fills": len(result.fills)}
        return obs, reward, terminated, False, info
